"""Persistent owned terrain lease: info, begin, pages, end, acknowledged exit."""

from PySide6.QtCore import QObject,QProcess,QTimer,Signal
from .framing import Decoder,encode_request
from .terrain_scene import SceneAssembler,MAX_PAGE


class TerrainSession(QObject):
    changed=Signal()
    completed=Signal(object)

    def __init__(self,engine_path,coordinator,references,parent=None):
        super().__init__(parent)
        self.engine_path,self.coordinator,self.references=engine_path,coordinator,references
        self.process=None;self.pending=None;self.active=None;self.scene=None
        self.phase='idle';self.status='No terrain requested.';self._cancelled=False;self._completed=None
        self.expected='';self.decoder=None;self.diagnostic_bytes=0
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self._timeout)
        self.exit_timer=QTimer(self);self.exit_timer.setSingleShot(True);self.exit_timer.timeout.connect(self._exit_timeout)
        coordinator.changed.connect(self._lease_changed)

    @property
    def busy(self):return self.process is not None or self.pending is not None

    def request(self,request):
        self.pending=request
        if self.process:self._stop('Superseding the previous terrain request.')
        else:self._start()

    def _lease_changed(self):
        if self.pending and not self.coordinator.busy:QTimer.singleShot(0,self._start)

    def _start(self):
        if self.pending is None or self.coordinator.busy:return
        self.active=self.pending;self.pending=None;self.scene=None;self._completed=None;self._cancelled=False
        try:
            if not self.references.root:raise ValueError('Select an explicit reference directory before loading 3D shapes.')
            args=self.references.engine_arguments()
            if not self.engine_path.is_file():raise ValueError('Terrain engine executable is unavailable.')
        except (ValueError,OSError) as error:
            self.status=str(error);self.phase='unavailable';self.changed.emit();return
        process=self.coordinator.acquire(self);self.process=process
        self.decoder=Decoder(MAX_PAGE,lambda size:self.scene.reserve_decode(size) if self.scene else None)
        self.diagnostic_bytes=0;self.phase='starting';self.status='Starting verified terrain session…'
        process.setProgram(str(self.engine_path));process.setArguments(args)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.started.connect(lambda:self._started(process))
        process.readyReadStandardOutput.connect(lambda:self._read(process))
        process.readyReadStandardError.connect(lambda:self._diagnostics(process))
        process.finished.connect(lambda code,status:self._finished(process,code,status))
        process.errorOccurred.connect(lambda error:self._failed_start(process,error))
        self.timer.start(30000);process.start();self.changed.emit()

    def _started(self,process):
        if process is not self.process:return
        if self._cancelled:process.kill();return
        self._send('info','engine.info',{})

    def _send(self,phase,method,params):
        if self.process is None or self._cancelled:return
        self.phase=phase
        suffix=f'page:{self.scene.cursor}' if phase=='page' else phase
        self.expected=f'terrain:{self.active.generation}:{suffix}'
        data=encode_request(self.expected,method,params)
        if self.process.write(data)!=len(data):raise ValueError('Terrain request was not fully queued')

    def _next(self):
        if self.scene.cursor<len(self.scene.manifest['pages']):
            self.status=f'Reading terrain page {self.scene.cursor+1} of {len(self.scene.manifest["pages"])}…'
            self._send('page','world.terrain_page',{**self.scene.identity,'pageIndex':self.scene.cursor})
        else:
            self.status='Releasing engine scene staging…'
            self._send('end','world.terrain_end',self.scene.identity)
        self.changed.emit()

    def _read(self,process):
        if process is not self.process:return
        if self._cancelled:process.read(65536);return
        try:
            replies=self.decoder.feed(bytes(process.read(65536)))
            for reply,size in zip(replies,self.decoder.last_frame_sizes):
                if reply.get('id')!=self.expected:raise ValueError('Unexpected terrain response identity')
                if 'error' in reply:
                    error=reply['error']
                    if not isinstance(error,dict):raise ValueError('Invalid terrain error')
                    raise ValueError(str(error.get('code','terrain_error'))+': '+str(error.get('message','Operation unavailable'))[:300])
                result=reply['result']
                if not isinstance(result,dict):raise ValueError('Invalid terrain result object')
                if self.phase=='info':
                    if type(result.get('protocolVersion')) is not int or result['protocolVersion']!=1 or not isinstance(result.get('methods'),list):
                        raise ValueError('Invalid terrain engine handshake')
                    if not self.references.accept_summary(result.get('reference')):raise ValueError(self.references.status)
                    if not all(method in result.get('methods',[]) for method in ('world.terrain_begin','world.terrain_page','world.terrain_end')):
                        raise ValueError('The engine has verified references but terrain streaming is not implemented in this build.')
                    self.status='Reading an immutable bounded source set…'
                    self._send('begin','world.terrain_begin',self.active.params())
                elif self.phase=='begin':
                    self.scene=SceneAssembler(result,self.active,size);self._next()
                elif self.phase=='page':
                    self.scene.accept_page(result,size);self._next()
                elif self.phase=='end':
                    self._completed=self.scene.finish(result,size)
                    self.phase='exit';self.status='Waiting for engine scene-release exit acknowledgement…'
                    process.closeWriteChannel();self.exit_timer.start(3000)
                else:raise ValueError('Terrain reply arrived in the wrong phase')
            if process.bytesAvailable() and not self._cancelled:QTimer.singleShot(0,lambda:self._read(process))
            self.changed.emit()
        except (ValueError,TypeError,KeyError,OverflowError,RecursionError,OSError) as error:
            self._completed=None;self._stop(str(error))

    def _diagnostics(self,process):
        if process is not self.process:return
        process.setReadChannel(QProcess.ProcessChannel.StandardError)
        self.diagnostic_bytes+=len(process.read(8192));remaining=process.bytesAvailable()
        process.setReadChannel(QProcess.ProcessChannel.StandardOutput)
        if self.diagnostic_bytes>65536:self._stop('Terrain engine diagnostics exceeded the bounded limit.')
        elif remaining:QTimer.singleShot(0,lambda:self._diagnostics(process))

    def _stop(self,message):
        self._cancelled=True;self._completed=None;self.status=message;self.timer.stop()
        if self.process:
            self.phase='stopping';self.process.kill();self.exit_timer.start(3000)
        else:self.phase='unavailable'
        self.changed.emit()

    def cancel(self):
        self.pending=None
        self._stop('Cancel requested; waiting for the owned terrain engine to stop.')

    def _timeout(self):self._stop('Terrain read exceeded the 30-second overall deadline.')
    def _exit_timeout(self):
        if self.process:
            if not self._cancelled:self._stop('Terrain engine did not exit after scene release.')
            else:
                self.status='Terrain engine stop has not been acknowledged. Wait or cancel closing.'
                self.changed.emit()

    def _failed_start(self,process,error):
        if process is self.process and error==QProcess.ProcessError.FailedToStart:
            self.status='Terrain engine could not start.';self._cancelled=True
            self._finished(process,-1,QProcess.ExitStatus.CrashExit)

    def _finished(self,process,code,status):
        if process is not self.process:return
        self.timer.stop();self.exit_timer.stop()
        completed=self._completed if not self._cancelled and self.phase=='exit' and code==0 and status==QProcess.ExitStatus.NormalExit else None
        self.process=None;self.coordinator.release(self,process)
        if completed:
            self.phase='complete';self.status='Validated source data received; geometry is not yet submitted.'
            self.completed.emit(completed)
        elif not self._cancelled:
            self.phase='unavailable';self.status='Terrain engine exited before complete scene delivery.'
        else:self.phase='canceled' if self.status.startswith('Cancel') else 'unavailable'
        self.scene=None;self._completed=None;self.changed.emit()
        if self.pending:QTimer.singleShot(0,self._start)

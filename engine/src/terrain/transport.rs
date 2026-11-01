use super::Session;
use serde_json::json;
use std::{
    io::{Read, Write},
    sync::mpsc::{sync_channel, RecvTimeoutError},
};
enum Input {
    Frame(Vec<u8>),
    Eof,
    Invalid,
}
fn read_frame(input: &mut impl Read) -> std::io::Result<Option<Vec<u8>>> {
    let mut header = [0; 4];
    if input.read(&mut header[..1])? == 0 {
        return Ok(None);
    }
    input.read_exact(&mut header[1..])?;
    let size = u32::from_be_bytes(header) as usize;
    if size == 0 || size > crate::protocol::MAX_FRAME {
        return Err(std::io::ErrorKind::InvalidData.into());
    }
    let mut bytes = Vec::new();
    bytes
        .try_reserve_exact(size)
        .map_err(|_| std::io::ErrorKind::OutOfMemory)?;
    bytes.resize(size, 0);
    input.read_exact(&mut bytes)?;
    Ok(Some(bytes))
}
/// The executable owns the input thread; a timed return requires process exit
/// to release an OS-blocked stdin reader. It owns no scene or source handles.
pub fn serve(
    mut input: impl Read + Send + 'static,
    mut output: impl Write,
    mut session: Session,
) -> std::io::Result<()> {
    let (tx, rx) = sync_channel(1);
    let _reader = std::thread::spawn(move || loop {
        let message = match read_frame(&mut input) {
            Ok(Some(bytes)) => Input::Frame(bytes),
            Ok(None) => Input::Eof,
            Err(_) => Input::Invalid,
        };
        let terminal = !matches!(message, Input::Frame(_));
        if tx.send(message).is_err() || terminal {
            break;
        }
    });
    loop {
        let message = if let Some(wait) = session.wait_remaining() {
            if wait.is_zero() {
                session.release();
                return Err(std::io::Error::new(
                    std::io::ErrorKind::TimedOut,
                    "terrain_session_expired",
                ));
            }
            match rx.recv_timeout(wait) {
                Ok(v) => v,
                Err(RecvTimeoutError::Timeout) => {
                    session.release();
                    return Err(std::io::Error::new(
                        std::io::ErrorKind::TimedOut,
                        "terrain_session_expired",
                    ));
                }
                Err(_) => {
                    session.release();
                    return Ok(());
                }
            }
        } else {
            match rx.recv() {
                Ok(v) => v,
                Err(_) => {
                    session.release();
                    return Ok(());
                }
            }
        };
        let bytes = match message {
            Input::Frame(v) => v,
            Input::Eof => {
                session.release();
                return Ok(());
            }
            Input::Invalid => {
                session.release();
                return Err(std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    "invalid_protocol_frame",
                ));
            }
        };
        let request = crate::registry::parse_protocol(&bytes);
        drop(bytes);
        let response = match request {
            Ok(v) => session.dispatch(v),
            Err(_) => {
                session.release();
                json!({"version":1,"id":null,"error":{"code":"invalid_json","message":"Invalid JSON request"}})
            }
        };
        let bytes = serde_json::to_vec(&response)?;
        if bytes.len() > crate::protocol::MAX_FRAME {
            session.release();
            return Err(std::io::ErrorKind::InvalidData.into());
        }
        output.write_all(&(bytes.len() as u32).to_be_bytes())?;
        output.write_all(&bytes)?;
        output.flush()?;
    }
}

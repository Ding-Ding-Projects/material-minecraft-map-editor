"""Synthetic bounded official-reference mechanics; no server execution."""
from __future__ import annotations
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import java_reference as reference


def archive(entries):
    out=io.BytesIO()
    with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for name,data in entries:
            z.writestr(name,data)
    return out.getvalue()


def version(version_id="1.20.1",world=3465):
    return json.dumps({"id":version_id,"world_version":world}).encode()


def test_direct_and_bundled_version_metadata():
    direct=archive([("version.json",version())])
    assert reference.inspect_server(direct,"1.20.1")["worldVersion"]==3465
    nested=archive([("version.json",version())])
    sha=hashlib.sha256(nested).hexdigest()
    outer=archive([("META-INF/versions.list",f"{sha}\t1.20.1\t1.20.1/server.jar\n"),("META-INF/versions/1.20.1/server.jar",nested)])
    result=reference.inspect_server(outer,"1.20.1")
    assert result["nestedJarSha256"]==sha
    assert result["worldVersion"]==3465


@pytest.mark.parametrize("payload",[version(world=True),version(world="3465"),version("other"),b'{"id":"1.20.1"}',b"x"*65537], ids=["bool","string","wrong-id","missing","oversized"])
def test_invalid_version_fields(payload):
    with pytest.raises(reference.ReferenceError):
        reference.inspect_server(archive([("version.json",payload)]),"1.20.1")


def test_nested_hash_and_traversal_are_rejected():
    nested=archive([("version.json",version())])
    for path,sha in [("1.20.1/server.jar","0"*64),("../server.jar",hashlib.sha256(nested).hexdigest())]:
        outer=archive([("META-INF/versions.list",f"{sha}\t1.20.1\t{path}\n"),("META-INF/versions/"+path,nested)])
        with pytest.raises(reference.ReferenceError):reference.inspect_server(outer,"1.20.1")
    duplicate=archive([("version.json",version()),("version.json",version())])
    with pytest.raises(reference.ReferenceError):reference.inspect_server(duplicate,"1.20.1")


@pytest.mark.parametrize("url",["http://piston-data.mojang.com/server.jar","https://example.com/server.jar","https://piston-data.mojang.com.evil.invalid/x","https://user@piston-data.mojang.com/x","https://piston-data.mojang.com:444/x","https://piston-data.mojang.com/x?q=1"])
def test_nonofficial_or_unsafe_urls(url):
    with pytest.raises(reference.ReferenceError):reference.validate_url(url)


def test_pinned_digest_and_size():
    reference.pinned(b"fixture",hashlib.sha1(b"fixture").hexdigest(),"sha1",7)
    with pytest.raises(reference.ReferenceError):reference.pinned(b"fixture","0"*40,"sha1")
    with pytest.raises(reference.ReferenceError):reference.pinned(b"fixture",hashlib.sha1(b"fixture").hexdigest(),"sha1",8)


def test_download_bounds_and_final_redirect_validation(monkeypatch):
    class Response:
        headers={}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def geturl(self):return "https://piston-data.mojang.com/fixture"
        def read(self,n):return b"x"*n
    class Opener:
        def open(self,*args,**kwargs):return Response()
    monkeypatch.setattr(reference.urllib.request,"build_opener",lambda *args:Opener())
    with pytest.raises(reference.ReferenceError):reference.fetch("https://piston-data.mojang.com/fixture",10)
    monkeypatch.setattr(Response,"geturl",lambda self:"https://example.invalid/fixture")
    with pytest.raises(reference.ReferenceError):reference.fetch("https://piston-data.mojang.com/fixture",10)


def test_acquisition_cache_reuse_and_real_hash_pipeline(tmp_path,monkeypatch):
    binary=archive([("version.json",version())])
    metadata=json.dumps({"id":"1.20.1","downloads":{"server":{"url":"https://piston-data.mojang.com/server.jar","sha1":hashlib.sha1(binary).hexdigest(),"size":len(binary)}}}).encode()
    manifest=tmp_path/"frozen.json"
    manifest.write_text(json.dumps({"schemaVersion":1,"versions":[{"id":"1.20.1","metadataUrl":"https://piston-meta.mojang.com/version.json","metadataSha1":hashlib.sha1(metadata).hexdigest()}]}))
    cache=tmp_path/"cache";cache.mkdir()
    monkeypatch.setattr(reference,"ignored_cache",lambda *args:cache)
    calls=[]
    def fetch(url,limit):
        calls.append(url)
        return metadata if "piston-meta" in url else binary
    monkeypatch.setattr(reference,"fetch",fetch)
    result=reference.acquire(manifest,tmp_path)
    assert result["worldVersion"]==3465
    assert result["serverSha256"]==hashlib.sha256(binary).hexdigest()
    assert result["executed"] is False
    reference.acquire(manifest,tmp_path)
    assert len(calls)==2
    (cache/"server.jar").write_bytes(b"tampered")
    with pytest.raises(reference.ReferenceError):reference.acquire(manifest,tmp_path)
    assert len(calls)==2


def test_unignored_cache_fails_before_creating_directory(tmp_path,monkeypatch):
    class Result:returncode=1
    monkeypatch.setattr(reference.subprocess,"run",lambda *args,**kwargs:Result())
    with pytest.raises(reference.ReferenceError):reference.ignored_cache(tmp_path,"1.20.1")
    assert not (tmp_path/"build").exists()



def test_zip_directory_budget_is_checked_before_member_parsing():
    data=bytearray(archive([("version.json",version())]))
    end=data.rfind(b"PK\x05\x06")
    reference.struct.pack_into("<H",data,end+8,65535)
    reference.struct.pack_into("<H",data,end+10,65535)
    with pytest.raises(reference.ReferenceError,match="ZIP directory"):
        reference.inspect_server(bytes(data),"1.20.1")


def test_redirect_handler_rejects_unapproved_intermediate_target():
    with pytest.raises(reference.ReferenceError):
        reference.OfficialRedirects().redirect_request(None,None,302,"redirect",{},"https://example.invalid/server.jar")

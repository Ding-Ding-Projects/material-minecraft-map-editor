use serde_json::{json, Value};
use std::io::{Read, Write};
pub const MAX_FRAME: usize = 1024 * 1024;
pub fn serve(input: impl Read, output: impl Write) -> std::io::Result<()> {
    serve_with_reference(
        input,
        output,
        &crate::reference::Availability::Unavailable("reference_root_missing"),
    )
}
pub fn serve_with_reference(
    mut input: impl Read,
    mut output: impl Write,
    reference: &crate::reference::Availability,
) -> std::io::Result<()> {
    loop {
        let mut header = [0; 4];
        match input.read(&mut header[..1])? {
            0 => return Ok(()),
            _ => input.read_exact(&mut header[1..])?,
        };
        let n = u32::from_be_bytes(header) as usize;
        if n == 0 || n > MAX_FRAME {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                "invalid frame length",
            ));
        }
        let mut bytes = vec![0; n];
        input.read_exact(&mut bytes)?;
        let response = match serde_json::from_slice::<Value>(&bytes) {
            Ok(request) => dispatch_with_reference(request, Some(reference)),
            Err(_) => {
                json!({"version":1,"id":null,"error":{"code":"invalid_json","message":"Invalid JSON request"}})
            }
        };
        let bytes = serde_json::to_vec(&response)?;
        output.write_all(&(bytes.len() as u32).to_be_bytes())?;
        output.write_all(&bytes)?;
        output.flush()?;
    }
}
pub fn dispatch(request: Value) -> Value {
    dispatch_with_reference(request, None)
}
pub fn dispatch_with_reference(
    request: Value,
    reference: Option<&crate::reference::Availability>,
) -> Value {
    let id = request.get("id").cloned().unwrap_or(Value::Null);
    let fail = |code: &str, message: &str| json!({"version":1,"id":id,"error":{"code":code,"message":message}});
    if !request.is_object()
        || request.get("version").and_then(Value::as_u64) != Some(1)
        || !(id.is_string() || id.is_i64() || id.is_u64())
        || id.as_str().is_some_and(|v| v.len() > 128)
    {
        return json!({"version":1,"id":null,"error":{"code":"invalid_request","message":"Expected protocol version 1 and bounded string or integer id"}});
    }
    let result = match request.get("method").and_then(Value::as_str) {
        Some("engine.info") => {
            json!({"name":"material-world-engine","version":env!("CARGO_PKG_VERSION"),"protocolVersion":1,"methods":["engine.info","world.probe","world.dimensions","world.chunk_summary"],"editingSupported":false,"formats":["java-nbt","java-region-structural"],"reference":reference.map(|r|r.summary()).unwrap_or_else(||json!({"status":"unavailable","reasonCode":"reference_root_missing"}))})
        }
        Some("world.probe") => {
            let Some(path) = request.pointer("/params/path").and_then(Value::as_str) else {
                return fail("invalid_params", "Expected params.path");
            };
            if path.is_empty() || path.len() > 32768 || path.contains('\0') {
                return fail("invalid_params", "Invalid path");
            }
            match crate::world::probe(std::path::Path::new(path)) {
                Ok(v) => v,
                Err(message) => return fail("probe_failed", message),
            }
        }
        Some(method @ ("world.dimensions" | "world.chunk_summary")) => {
            let Some(path) = request.pointer("/params/path").and_then(Value::as_str) else {
                return fail("invalid_params", "Expected params.path");
            };
            if path.is_empty() || path.len() > 32768 || path.contains('\0') {
                return fail("invalid_params", "Invalid path");
            }
            let result = if method == "world.dimensions" {
                crate::world_read::dimensions(std::path::Path::new(path))
            } else {
                let Some(dimension) = request.pointer("/params/dimension").and_then(Value::as_str)
                else {
                    return fail("invalid_params", "Expected dimension identifier");
                };
                let x = request
                    .pointer("/params/chunkX")
                    .and_then(Value::as_i64)
                    .and_then(|n| i32::try_from(n).ok());
                let z = request
                    .pointer("/params/chunkZ")
                    .and_then(Value::as_i64)
                    .and_then(|n| i32::try_from(n).ok());
                let (Some(x), Some(z)) = (x, z) else {
                    return fail("invalid_params", "Expected signed 32-bit chunk coordinates");
                };
                crate::world_read::chunk_summary(std::path::Path::new(path), dimension, x, z)
            };
            match result {
                Ok(v) => v,
                Err(message) => return fail("world_read_failed", message),
            }
        }
        _ => return fail("method_not_found", "Unsupported method"),
    };
    crate::world_read::bounded_response(json!({"version":1,"id":id,"result":result}), &id)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn framed_multiple_requests_and_malformed_frames() {
        let request = br#"{"version":1,"id":"hello","method":"engine.info"}"#;
        let mut input = Vec::new();
        for _ in 0..2 {
            input.extend_from_slice(&(request.len() as u32).to_be_bytes());
            input.extend_from_slice(request);
        }
        let mut output = Vec::new();
        serve(&input[..], &mut output).unwrap();
        let n = u32::from_be_bytes(output[..4].try_into().unwrap()) as usize;
        let v: Value = serde_json::from_slice(&output[4..4 + n]).unwrap();
        assert_eq!(v["id"], "hello");
        assert_eq!(v["result"]["editingSupported"], false);
        assert!(output.len() > n + 4);
        for bad in [&[0][..], &[0, 0, 0, 0], &[0, 16, 0, 1], &[0, 0, 0, 2, 123]] {
            assert!(serve(bad, Vec::new()).is_err());
        }
    }
    #[test]
    fn invalid_protocol_and_unsupported_methods() {
        assert_eq!(
            dispatch(json!({"version":2,"id":1,"method":"engine.info"}))["error"]["code"],
            "invalid_request"
        );
        assert_eq!(
            dispatch(json!({"version":1,"id":1,"method":"world.edit"}))["error"]["code"],
            "method_not_found"
        );
    }
}

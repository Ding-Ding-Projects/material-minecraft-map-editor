use serde::de::{DeserializeSeed, Error, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Number, Value};
struct Seed<'a> {
    left: &'a mut usize,
    max_string: usize,
}
struct Bounded<'a> {
    left: &'a mut usize,
    max_string: usize,
}
impl<'de> DeserializeSeed<'de> for Seed<'_> {
    type Value = Value;
    fn deserialize<D: serde::Deserializer<'de>>(self, d: D) -> Result<Value, D::Error> {
        *self.left = self
            .left
            .checked_sub(1)
            .ok_or_else(|| D::Error::custom("JSON node limit"))?;
        d.deserialize_any(Bounded {
            left: self.left,
            max_string: self.max_string,
        })
    }
}
impl<'de> Visitor<'de> for Bounded<'_> {
    type Value = Value;
    fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        f.write_str("bounded unique-key JSON")
    }
    fn visit_bool<E: Error>(self, v: bool) -> Result<Value, E> {
        Ok(Value::Bool(v))
    }
    fn visit_i64<E: Error>(self, v: i64) -> Result<Value, E> {
        Ok(Value::Number(v.into()))
    }
    fn visit_u64<E: Error>(self, v: u64) -> Result<Value, E> {
        Ok(Value::Number(v.into()))
    }
    fn visit_f64<E: Error>(self, v: f64) -> Result<Value, E> {
        Ok(Value::Number(
            Number::from_f64(v).ok_or_else(|| E::custom("invalid number"))?,
        ))
    }
    fn visit_unit<E: Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }
    fn visit_str<E: Error>(self, v: &str) -> Result<Value, E> {
        if v.len() > self.max_string {
            return Err(E::custom("string limit"));
        }
        Ok(Value::String(v.into()))
    }
    fn visit_string<E: Error>(self, v: String) -> Result<Value, E> {
        self.visit_str(&v)
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Value, A::Error> {
        let mut out = Vec::new();
        while let Some(value) = seq.next_element_seed(Seed {
            left: self.left,
            max_string: self.max_string,
        })? {
            if out.len() == 65536 {
                return Err(A::Error::custom("array limit"));
            }
            out.push(value);
        }
        Ok(Value::Array(out))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Value, A::Error> {
        let mut out = Map::new();
        while let Some(key) = map.next_key::<String>()? {
            if key.len() > self.max_string || out.len() == 65536 || out.contains_key(&key) {
                return Err(A::Error::custom("invalid or duplicate key"));
            }
            let value = map.next_value_seed(Seed {
                left: self.left,
                max_string: self.max_string,
            })?;
            out.insert(key, value);
        }
        Ok(Value::Object(out))
    }
}
pub(super) fn parse(bytes: &[u8], limit: usize) -> Result<Value, &'static str> {
    parse_with_string_limit(bytes, limit, 256)
}
pub(super) fn parse_with_string_limit(
    bytes: &[u8],
    limit: usize,
    max_string: usize,
) -> Result<Value, &'static str> {
    parse_with_limits(bytes, limit, max_string, 500000)
}
pub(super) fn parse_with_limits(
    bytes: &[u8],
    limit: usize,
    max_string: usize,
    mut nodes: usize,
) -> Result<Value, &'static str> {
    if bytes.len() > limit {
        return Err("registry JSON byte limit exceeded");
    }
    let (mut depth, mut quoted, mut escaped) = (0usize, false, false);
    for &b in bytes {
        if quoted {
            if escaped {
                escaped = false;
            } else if b == b'\\' {
                escaped = true;
            } else if b == b'"' {
                quoted = false;
            }
        } else {
            match b {
                b'"' => quoted = true,
                b'{' | b'[' => {
                    depth += 1;
                    if depth > 16 {
                        return Err("registry JSON depth limit exceeded");
                    }
                }
                b'}' | b']' => depth = depth.checked_sub(1).ok_or("invalid registry JSON")?,
                _ => (),
            }
        }
    }
    let mut d = serde_json::Deserializer::from_slice(bytes);
    let value = Seed {
        left: &mut nodes,
        max_string,
    }
    .deserialize(&mut d)
    .map_err(|_| "invalid, duplicate-key or oversized registry JSON")?;
    d.end().map_err(|_| "trailing registry JSON")?;
    Ok(value)
}

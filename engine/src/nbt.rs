//! Lossless Java NBT structure. Strings retain original modified UTF-8 bytes.
#[derive(Clone, Debug, PartialEq)]
pub struct NamedTag {
    pub name: Vec<u8>,
    pub tag: Tag,
}
#[derive(Clone, Debug, PartialEq)]
pub enum Tag {
    Byte(i8),
    Short(i16),
    Int(i32),
    Long(i64),
    Float(u32),
    Double(u64),
    ByteArray(Vec<u8>),
    String(Vec<u8>),
    List(u8, Vec<Tag>),
    Compound(Vec<NamedTag>),
    IntArray(Vec<i32>),
    LongArray(Vec<i64>),
}
#[derive(Clone, Copy)]
pub struct Limits {
    pub bytes: usize,
    pub depth: usize,
    pub elements: usize,
}
impl Default for Limits {
    fn default() -> Self {
        Self {
            bytes: 64 * 1024 * 1024,
            depth: 64,
            elements: 1_000_000,
        }
    }
}
pub type Result<T> = std::result::Result<T, &'static str>;
impl Tag {
    pub fn id(&self) -> u8 {
        match self {
            Self::Byte(_) => 1,
            Self::Short(_) => 2,
            Self::Int(_) => 3,
            Self::Long(_) => 4,
            Self::Float(_) => 5,
            Self::Double(_) => 6,
            Self::ByteArray(_) => 7,
            Self::String(_) => 8,
            Self::List(_, _) => 9,
            Self::Compound(_) => 10,
            Self::IntArray(_) => 11,
            Self::LongArray(_) => 12,
        }
    }
}
struct Reader<'a> {
    data: &'a [u8],
    at: usize,
    left: usize,
    limits: Limits,
}
impl Reader<'_> {
    fn take(&mut self, n: usize) -> Result<&[u8]> {
        let end = self.at.checked_add(n).ok_or("length overflow")?;
        let v = self.data.get(self.at..end).ok_or("truncated NBT")?;
        self.at = end;
        Ok(v)
    }
    fn byte(&mut self) -> Result<u8> {
        Ok(self.take(1)?[0])
    }
    fn count(&mut self, n: usize) -> Result<()> {
        self.left = self.left.checked_sub(n).ok_or("element budget exceeded")?;
        Ok(())
    }
    fn string(&mut self) -> Result<Vec<u8>> {
        let n = u16::from_be_bytes(self.take(2)?.try_into().unwrap()) as usize;
        Ok(self.take(n)?.to_vec())
    }
    fn length(&mut self) -> Result<usize> {
        let n = i32::from_be_bytes(self.take(4)?.try_into().unwrap());
        if n < 0 {
            return Err("negative length");
        }
        let n = n as usize;
        self.count(n)?;
        Ok(n)
    }
    fn tag(&mut self, id: u8, depth: usize) -> Result<Tag> {
        if depth > self.limits.depth {
            return Err("depth budget exceeded");
        }
        self.count(1)?;
        Ok(match id {
            1 => Tag::Byte(self.byte()? as i8),
            2 => Tag::Short(i16::from_be_bytes(self.take(2)?.try_into().unwrap())),
            3 => Tag::Int(i32::from_be_bytes(self.take(4)?.try_into().unwrap())),
            4 => Tag::Long(i64::from_be_bytes(self.take(8)?.try_into().unwrap())),
            5 => Tag::Float(u32::from_be_bytes(self.take(4)?.try_into().unwrap())),
            6 => Tag::Double(u64::from_be_bytes(self.take(8)?.try_into().unwrap())),
            7 => {
                let n = self.length()?;
                Tag::ByteArray(self.take(n)?.to_vec())
            }
            8 => Tag::String(self.string()?),
            9 => {
                let kind = self.byte()?;
                let n = self.length()?;
                if kind > 12 || (kind == 0 && n != 0) {
                    return Err("invalid list type");
                }
                let mut v = Vec::new();
                for _ in 0..n {
                    v.push(self.tag(kind, depth + 1)?);
                }
                Tag::List(kind, v)
            }
            10 => {
                let mut v = Vec::new();
                loop {
                    let kind = self.byte()?;
                    if kind == 0 {
                        break;
                    }
                    let name = self.string()?;
                    v.push(NamedTag {
                        name,
                        tag: self.tag(kind, depth + 1)?,
                    });
                }
                Tag::Compound(v)
            }
            11 => {
                let n = self.length()?;
                let mut v = Vec::new();
                for _ in 0..n {
                    v.push(i32::from_be_bytes(self.take(4)?.try_into().unwrap()));
                }
                Tag::IntArray(v)
            }
            12 => {
                let n = self.length()?;
                let mut v = Vec::new();
                for _ in 0..n {
                    v.push(i64::from_be_bytes(self.take(8)?.try_into().unwrap()));
                }
                Tag::LongArray(v)
            }
            _ => return Err("unknown NBT type"),
        })
    }
}
pub fn parse(data: &[u8], limits: Limits) -> Result<NamedTag> {
    if data.len() > limits.bytes {
        return Err("byte budget exceeded");
    }
    let mut r = Reader {
        data,
        at: 0,
        left: limits.elements,
        limits,
    };
    let id = r.byte()?;
    if id != 10 {
        return Err("root must be compound");
    }
    let name = r.string()?;
    let tag = r.tag(id, 0)?;
    if r.at != data.len() {
        return Err("trailing NBT bytes");
    }
    Ok(NamedTag { name, tag })
}
struct Writer {
    data: Vec<u8>,
    left: usize,
    limits: Limits,
}
impl Writer {
    fn put(&mut self, b: &[u8]) -> Result<()> {
        if self
            .data
            .len()
            .checked_add(b.len())
            .ok_or("length overflow")?
            > self.limits.bytes
        {
            return Err("byte budget exceeded");
        }
        self.data.extend_from_slice(b);
        Ok(())
    }
    fn count(&mut self, n: usize) -> Result<()> {
        self.left = self.left.checked_sub(n).ok_or("element budget exceeded")?;
        Ok(())
    }
    fn string(&mut self, s: &[u8]) -> Result<()> {
        let n = u16::try_from(s.len()).map_err(|_| "string too long")?;
        self.put(&n.to_be_bytes())?;
        self.put(s)
    }
    fn length(&mut self, n: usize) -> Result<()> {
        self.count(n)?;
        let n = i32::try_from(n).map_err(|_| "array too long")?;
        self.put(&n.to_be_bytes())
    }
    fn tag(&mut self, t: &Tag, d: usize) -> Result<()> {
        if d > self.limits.depth {
            return Err("depth budget exceeded");
        }
        self.count(1)?;
        match t {
            Tag::Byte(v) => self.put(&[*v as u8]),
            Tag::Short(v) => self.put(&v.to_be_bytes()),
            Tag::Int(v) => self.put(&v.to_be_bytes()),
            Tag::Long(v) => self.put(&v.to_be_bytes()),
            Tag::Float(v) => self.put(&v.to_be_bytes()),
            Tag::Double(v) => self.put(&v.to_be_bytes()),
            Tag::ByteArray(v) => {
                self.length(v.len())?;
                self.put(v)
            }
            Tag::String(v) => self.string(v),
            Tag::List(k, v) => {
                if *k > 12 || (*k == 0 && !v.is_empty()) || v.iter().any(|t| t.id() != *k) {
                    return Err("invalid list type");
                }
                self.put(&[*k])?;
                self.length(v.len())?;
                for t in v {
                    self.tag(t, d + 1)?;
                }
                Ok(())
            }
            Tag::Compound(v) => {
                for t in v {
                    self.put(&[t.tag.id()])?;
                    self.string(&t.name)?;
                    self.tag(&t.tag, d + 1)?;
                }
                self.put(&[0])
            }
            Tag::IntArray(v) => {
                self.length(v.len())?;
                for n in v {
                    self.put(&n.to_be_bytes())?;
                }
                Ok(())
            }
            Tag::LongArray(v) => {
                self.length(v.len())?;
                for n in v {
                    self.put(&n.to_be_bytes())?;
                }
                Ok(())
            }
        }
    }
}
pub fn write(root: &NamedTag, limits: Limits) -> Result<Vec<u8>> {
    if root.tag.id() != 10 {
        return Err("root must be compound");
    }
    let mut w = Writer {
        data: Vec::new(),
        left: limits.elements,
        limits,
    };
    w.put(&[10])?;
    w.string(&root.name)?;
    w.tag(&root.tag, 0)?;
    Ok(w.data)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn every_kind_roundtrips_bits_and_names() {
        let tags = vec![
            Tag::Byte(-3),
            Tag::Short(-50),
            Tag::Int(-5),
            Tag::Long(i64::MIN),
            Tag::Float(0x7fc00001),
            Tag::Double(0x7ff8000000000001),
            Tag::ByteArray(vec![0, 255]),
            Tag::String(vec![0xc0, 0x80, 0xed, 0xa0, 0x80]),
            Tag::List(3, vec![Tag::Int(4)]),
            Tag::Compound(vec![]),
            Tag::IntArray(vec![-1, 5]),
            Tag::LongArray(vec![i64::MAX]),
        ];
        let root = NamedTag {
            name: vec![],
            tag: Tag::Compound(
                tags.into_iter()
                    .map(|tag| NamedTag {
                        name: vec![0xc0, 0x80],
                        tag,
                    })
                    .collect(),
            ),
        };
        let bytes = write(&root, Limits::default()).unwrap();
        assert_eq!(parse(&bytes, Limits::default()).unwrap(), root);
        assert_eq!(
            write(
                &parse(&bytes, Limits::default()).unwrap(),
                Limits::default()
            )
            .unwrap(),
            bytes
        );
    }
    #[test]
    fn malformed_and_bounded() {
        for b in [
            &[10, 0][..],
            &[10, 0, 0, 7, 0, 0, 255, 255, 255, 255, 0],
            &[10, 0, 0, 13, 0, 0, 0],
            &[10, 0, 0, 0, 1],
        ] {
            assert!(parse(b, Limits::default()).is_err());
        }
        let b = [10, 0, 0, 10, 0, 0, 0, 0];
        assert!(parse(
            &b,
            Limits {
                depth: 0,
                ..Limits::default()
            }
        )
        .is_err());
        assert!(parse(
            &b,
            Limits {
                elements: 1,
                ..Limits::default()
            }
        )
        .is_err());
        assert!(parse(
            &b,
            Limits {
                bytes: 2,
                ..Limits::default()
            }
        )
        .is_err());
    }
    #[test]
    fn writer_rejects_mixed_list_and_budget() {
        let r = NamedTag {
            name: vec![],
            tag: Tag::Compound(vec![NamedTag {
                name: vec![],
                tag: Tag::List(1, vec![Tag::Int(2)]),
            }]),
        };
        assert!(write(&r, Limits::default()).is_err());
        assert!(write(
            &NamedTag {
                name: vec![],
                tag: Tag::Compound(vec![])
            },
            Limits {
                bytes: 3,
                ..Limits::default()
            }
        )
        .is_err());
    }
}

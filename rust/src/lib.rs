use std::cmp::Ordering;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Version {
    pub major: u64,
    pub minor: u64,
    pub patch: u64,
    pub prerelease: Option<String>,
    pub build: Option<String>,
}

fn numeric(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit())
}

fn identifiers(s: &str, prerelease: bool) -> bool {
    s.split('.').all(|part| {
        !part.is_empty()
            && part.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
            && !(prerelease && numeric(part) && part.len() > 1 && part.starts_with('0'))
    })
}

fn core_number(s: Option<&str>) -> Result<u64, String> {
    let s = s.ok_or_else(|| String::from("missing core component"))?;
    if !numeric(s) || (s.len() > 1 && s.starts_with('0')) {
        return Err(String::from("invalid core number"));
    }
    s.parse().map_err(|_| String::from("core number out of range"))
}

pub fn parse(s: &str) -> Result<Version, String> {
    let (rest, build) = match s.split_once('+') {
        Some((rest, build)) => {
            if !identifiers(build, false) {
                return Err(String::from("invalid build"));
            }
            (rest, Some(build.to_owned()))
        }
        None => (s, None),
    };
    let (core, prerelease) = match rest.split_once('-') {
        Some((core, pre)) => {
            if !identifiers(pre, true) {
                return Err(String::from("invalid prerelease"));
            }
            (core, Some(pre.to_owned()))
        }
        None => (rest, None),
    };
    let mut parts = core.split('.');
    let major = core_number(parts.next())?;
    let minor = core_number(parts.next())?;
    let patch = core_number(parts.next())?;
    if parts.next().is_some() {
        return Err(String::from("extra core component"));
    }
    Ok(Version { major, minor, patch, prerelease, build })
}

pub fn to_string(v: &Version) -> String {
    let mut s = format!("{}.{}.{}", v.major, v.minor, v.patch);
    if let Some(pre) = &v.prerelease {
        s.push('-');
        s.push_str(pre);
    }
    if let Some(build) = &v.build {
        s.push('+');
        s.push_str(build);
    }
    s
}

fn compare_identifier(a: &str, b: &str) -> Ordering {
    match (numeric(a), numeric(b)) {
        (true, true) => {
            let a = a.trim_start_matches('0');
            let b = b.trim_start_matches('0');
            a.len().cmp(&b.len()).then_with(|| a.cmp(b))
        }
        (true, false) => Ordering::Less,
        (false, true) => Ordering::Greater,
        (false, false) => a.cmp(b),
    }
}

pub fn compare(a: &Version, b: &Version) -> Ordering {
    let core = (a.major, a.minor, a.patch).cmp(&(b.major, b.minor, b.patch));
    if core != Ordering::Equal { return core; }
    match (&a.prerelease, &b.prerelease) {
        (None, None) => Ordering::Equal,
        (None, Some(_)) => Ordering::Greater,
        (Some(_), None) => Ordering::Less,
        (Some(a), Some(b)) => {
            let mut aa = a.split('.');
            let mut bb = b.split('.');
            loop {
                match (aa.next(), bb.next()) {
                    (None, None) => return Ordering::Equal,
                    (None, Some(_)) => return Ordering::Less,
                    (Some(_), None) => return Ordering::Greater,
                    (Some(x), Some(y)) => {
                        let order = compare_identifier(x, y);
                        if order != Ordering::Equal { return order; }
                    }
                }
            }
        }
    }
}

fn release(major: u64, minor: u64, patch: u64) -> Version {
    Version { major, minor, patch, prerelease: None, build: None }
}

pub fn bump_major(v: &Version) -> Version {
    release(v.major.saturating_add(1), 0, 0)
}

pub fn bump_minor(v: &Version) -> Version {
    release(v.major, v.minor.saturating_add(1), 0)
}

pub fn bump_patch(v: &Version) -> Version {
    release(v.major, v.minor, v.patch.saturating_add(1))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_reference_parts() -> Result<(), String> {
        let v = parse("1.2.3-alpha.1.2+build.11.e0f985a")?;
        assert_eq!((v.major, v.minor, v.patch), (1, 2, 3));
        assert_eq!(v.prerelease.as_deref(), Some("alpha.1.2"));
        assert_eq!(v.build.as_deref(), Some("build.11.e0f985a"));
        Ok(())
    }

    #[test]
    fn round_trips_reference_examples() -> Result<(), String> {
        for s in ["1.2.3-alpha-1+build.11.e0f985a", "0.1.0-0f", "0.0.0-0foo.1", "0.0.0-0foo.1+build.1", "1.2.3+001", "1.2.3--"] {
            assert_eq!(to_string(&parse(s)?), s);
        }
        Ok(())
    }

    #[test]
    fn rejects_invalid_versions() {
        for s in ["", "1", "1.2", "1.2.3.4", "01.2.3", "1.02.3", "1.2.03", "-1.2.3", "1.2.3-", "1.2.3+", "1.2.3-a..b", "1.2.3-01", "1.2.3+foo+bar", "1.2.3-a_b", "1.2.3\n", " 1.2.3", "1.2.3-é"] {
            assert!(parse(s).is_err(), "accepted {s:?}");
        }
    }

    #[test]
    fn follows_semver_precedence_chain() -> Result<(), String> {
        let cases = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"];
        for pair in cases.windows(2) {
            let a = parse(pair[0])?;
            let b = parse(pair[1])?;
            assert_eq!(compare(&a, &b), Ordering::Less);
            assert_eq!(compare(&b, &a), Ordering::Greater);
        }
        Ok(())
    }

    #[test]
    fn ignores_build_metadata() -> Result<(), String> {
        assert_eq!(compare(&parse("1.2.3+a")?, &parse("1.2.3+b")?), Ordering::Equal);
        assert_eq!(compare(&parse("1.2.3-rc.1+a")?, &parse("1.2.3-rc.1")?), Ordering::Equal);
        Ok(())
    }

    #[test]
    fn compares_unbounded_numeric_identifiers() -> Result<(), String> {
        assert_eq!(compare(&parse("1.0.0-999999999999999999999999")?, &parse("1.0.0-1000000000000000000000000")?), Ordering::Less);
        assert_eq!(compare(&parse("1.0.0-999999999999999999999999")?, &parse("1.0.0-a")?), Ordering::Less);
        Ok(())
    }

    #[test]
    fn bumps_clear_suffixes_and_reset_lower_parts() -> Result<(), String> {
        let v = parse("3.4.5-rc.1+build.7")?;
        assert_eq!(to_string(&bump_major(&v)), "4.0.0");
        assert_eq!(to_string(&bump_minor(&v)), "3.5.0");
        assert_eq!(to_string(&bump_patch(&v)), "3.4.6");
        assert_eq!(to_string(&v), "3.4.5-rc.1+build.7");
        Ok(())
    }
}

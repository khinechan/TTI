"""astro_core — the sky math. No charts, places or dates are built in: every function takes them as inputs.

Ephemeris: pyephem (apparent geocentric ecliptic longitude of date). Angles in degrees.
"""
import math
import datetime as dt
import ephem

UTC = dt.timezone.utc
BODY = {'Sun': ephem.Sun, 'Moon': ephem.Moon, 'Mercury': ephem.Mercury, 'Venus': ephem.Venus,
        'Mars': ephem.Mars, 'Jupiter': ephem.Jupiter, 'Saturn': ephem.Saturn,
        'Uranus': ephem.Uranus, 'Neptune': ephem.Neptune, 'Pluto': ephem.Pluto}
ASPECTS = {'☌': 0, '⚹': 60, '□': 90, '△': 120, '☍': 180}
SIGNS = ['Ari', 'Tau', 'Gem', 'Can', 'Leo', 'Vir', 'Lib', 'Sco', 'Sag', 'Cap', 'Aqu', 'Pis']


def _ed(t):
    """aware datetime -> ephem.Date (UTC)."""
    return ephem.Date(t.astimezone(UTC).replace(tzinfo=None))


def lon(body, t):
    """λ(body, t): apparent geocentric ecliptic longitude of date, degrees in [0, 360)."""
    b = BODY[body](); d = _ed(t); b.compute(d, epoch=d)
    e = ephem.Ecliptic(ephem.Equatorial(b.g_ra, b.g_dec, epoch=d), epoch=d)
    return math.degrees(e.lon) % 360.0


def speed(body, t, h=0.25):
    """dλ/dt in degrees per day, central difference over ±h days (negative = retrograde)."""
    a, b = lon(body, t - dt.timedelta(days=h)), lon(body, t + dt.timedelta(days=h))
    return sep(b, a) / (2 * h)


J2000_EPHEM = 36525.0       # the J2000.0 epoch (JD 2451545.0) in ephem's day count (ephem day 0 = JD 2415020.0)


def obliquity(t):
    """ε(t) = 23.439291° − 0.0130042° · T, T in Julian centuries from J2000.0."""
    T = (float(_ed(t)) - J2000_EPHEM) / 36525.0
    return 23.439291 - 0.0130042 * T


def angles(t, lat, lon_east):
    """(ASC, MC) for time t at a place. θ = local sidereal time (RAMC), ε = obliquity, φ = latitude.
       MC  = atan2(sin θ, cos θ · cos ε)
       ASC = atan2(cos θ, −(sin ε · tan φ + cos ε · sin θ))"""
    o = ephem.Observer(); o.lat, o.lon = str(lat), str(lon_east); o.date = _ed(t); o.pressure = 0
    th = float(o.sidereal_time()); eps = math.radians(obliquity(t)); phi = math.radians(lat)
    mc = math.degrees(math.atan2(math.sin(th), math.cos(th) * math.cos(eps))) % 360.0
    asc = math.degrees(math.atan2(math.cos(th), -(math.sin(eps) * math.tan(phi) + math.cos(eps) * math.sin(th)))) % 360.0
    return asc, mc


def sep(a, b):
    """Signed difference a − b, wrapped to (−180, 180]."""
    return ((a - b + 180.0) % 360.0) - 180.0


def distance(a, b):
    """δ = |sep(a, b)| ∈ [0, 180]: the angle between two longitudes."""
    return abs(sep(a, b))


def orb(a, b, A):
    """o = |δ − A|: how far two longitudes are from an exact aspect of A degrees."""
    return abs(distance(a, b) - A)


def best_aspect(a, b, orbs=None):
    """The tightest aspect between two longitudes within its orb: (symbol, orb) or None.
       orbs: {symbol: max orb}; default 3° for every aspect."""
    orbs = orbs or {s: 3.0 for s in ASPECTS}
    hits = [(orb(a, b, A), s) for s, A in ASPECTS.items() if orb(a, b, A) <= orbs[s]]
    return (min(hits)[1], min(hits)[0]) if hits else None


def applying(body, t, point, A, step_days=0.01):
    """True if the gap to the exact aspect shrinks over a short step at the body's own speed."""
    l, v = lon(body, t), speed(body, t)
    return orb(l + v * step_days, point, A) < orb(l, point, A)


def roots(f, t0, t1, step_min=10, tol_s=30):
    """Times in [t0, t1) where f(t) crosses zero (sign change, |f| < 90 at both ends), by bisection."""
    out = []; step = dt.timedelta(minutes=step_min); a = t0; fa = f(a)
    while a < t1:
        b = min(a + step, t1); fb = f(b)
        if fa == 0:
            out.append(a)
        elif fa * fb < 0 and abs(fa) < 90 and abs(fb) < 90:
            lo, hi, flo = a, b, fa
            while (hi - lo).total_seconds() > tol_s:
                m = lo + (hi - lo) / 2; fm = f(m)
                if flo * fm <= 0: hi = m
                else: lo, flo = m, fm
            out.append(lo + (hi - lo) / 2)
        a, fa = b, fb
    return out


def exact_times(body, point, A, t0, t1, step_min=60):
    """Times in [t0, t1) when the body is exactly A degrees from a fixed longitude (both sides)."""
    out = []
    for target in {(point + A) % 360, (point - A) % 360}:
        out += roots(lambda x: sep(lon(body, x), target), t0, t1, step_min=step_min)
    return sorted(out)


def chart_points(t, lat, lon_east):
    """Every body's longitude + ASC/MC/DSC/IC for a time and place (a chart)."""
    p = {b: lon(b, t) for b in BODY}
    p['ASC'], p['MC'] = angles(t, lat, lon_east)
    p['DSC'], p['IC'] = (p['ASC'] + 180) % 360, (p['MC'] + 180) % 360
    return p


def sign_of(l):
    """Zodiac sign index ⌊λ/30⌋ (0 = Aries) and degree within the sign."""
    return int(l // 30) % 12, l % 30


def fmt(l):
    s, d = sign_of(l)
    return "%.1f %s" % (d, SIGNS[s])

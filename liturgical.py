"""The Roman liturgical calendar, computed locally.

Dating an imported homily means turning a lectionary number into a date. That
used to require USCCB: fetch a day's page, read its number, repeat. It worked
until it didn't -- the site now refuses everything after the first request, on
any network, so throttling cannot fix it and a 403 is indistinguishable from
"no homily that day" unless you are careful.

None of it needed a network. Easter is a closed-form calculation, every movable
season follows from Easter, and the ferial lectionary numbers are arithmetic on
the season and weekday. So this module answers the same question offline, and
can be checked against the homilies whose dates are already known -- which a
scraper never could.

    lectionary_number(date)          -> the number for that day, or None
    dates_for_lectionary(n, around)  -> candidate dates, nearest first

What it covers: the temporal cycle (Advent, Christmas, Lent, Holy Week, Easter,
Ordinary Time), ferial and Sunday, plus the fixed solemnities and feasts that
appear in this archive. It does not know the whole sanctoral calendar; an
unknown number returns None rather than a guess.
"""

import datetime

_DAY = datetime.timedelta(days=1)

# Ferial numbering, verified against the dated homilies in this archive.
#
#   Ordinary Time    week N Monday = 305 + 6(N-1)          (Tue 10th of OT = 360)
#   Lent             week 1 Monday = 224, then 230 + 7(N-2) (Wed 3rd of Lent = 239)
#   Easter           week N Monday = 267 + 6(N-2)          (Wed 7th of Easter = 299)
#   Advent           week N Monday = 175 + 6(N-1)          (Wed 2nd of Advent = 183)
#
# Each block runs Monday..Saturday, so the weekday index is 0..5.
_OT_WEEK1_MONDAY = 305
# Lent steps by 6 into week 2 and by 7 thereafter: weeks 3, 4 and 5 each carry
# an extra entry for the Year A scrutiny readings. Fitted to the archive's own
# confirmed days, then checked against two files it had never seen -- lect 235
# lands on a Saturday and 246 on a Wednesday, and both timestamps agree.
_LENT_WEEK1_MONDAY = 224
_LENT_WEEK2_MONDAY = 230
_LENT_WEEK_STEP = 7
_EASTER_WEEK2_MONDAY = 267
_ADVENT_WEEK1_MONDAY = 175

_ASH_WEDNESDAY = 219            # then Thu/Fri/Sat = 220/221/222
_HOLY_WEEK_MONDAY = 257         # Mon/Tue/Wed of Holy Week = 257/258/259
_EASTER_OCTAVE_MONDAY = 261     # Mon..Sat of the octave = 261..266

# Sunday and solemnity numbers. Where a number varies by cycle it is (A, B, C).
_SUNDAY_ADVENT = {1: (1, 2, 3), 2: (4, 5, 6), 3: (7, 8, 9), 4: (10, 11, 12)}
_SUNDAY_LENT = {1: (22, 23, 24), 2: (25, 26, 27), 3: (28, 29, 30),
                4: (31, 32, 33), 5: (34, 35, 36)}
_SUNDAY_EASTER = {2: (43, 44, 45), 3: (46, 47, 48), 4: (49, 50, 51),
                  5: (52, 53, 54), 6: (55, 56, 57), 7: (58, 59, 60)}
_EASTER_SUNDAY = 42
_HOLY_THURSDAY = 39             # Evening Mass of the Lord's Supper
_GOOD_FRIDAY = 40
_EASTER_VIGIL = 41
_PENTECOST_DAY = 63
# The two Sundays that follow Pentecost, before Ordinary Time resumes counting.
_TRINITY = (164, 165, 166)
_CORPUS_CHRISTI = (167, 168, 169)
_HOLY_FAMILY = 17               # the Sunday in the octave of Christmas

# Weekdays of the Christmas octave and season. 26-28 December are feasts with
# numbers of their own (Stephen, John, the Holy Innocents).
_CHRISTMAS_WEEKDAYS = {(12, 26): 696, (12, 27): 697, (12, 28): 698,
                       (12, 29): 202, (12, 30): 203, (12, 31): 204,
                       (1, 2): 205, (1, 3): 206, (1, 4): 207, (1, 5): 208,
                       (1, 6): 209, (1, 7): 210}

# Fixed-date solemnities and feasts that displace the day's readings. The
# solemnities and feasts of the Lord here also displace an Ordinary Time Sunday;
# the memorials do not, and are not listed.
_FIXED = {
    (12, 25): 16,    # Christmas, Mass during the Day
    (1, 1): 18,      # Mary, Mother of God
    (2, 2): 524,     # The Presentation of the Lord
    (3, 19): 543,    # Joseph, Spouse of the BVM
    (3, 25): 545,    # The Annunciation
    (6, 24): 587,    # The Birth of John the Baptist (day)
    (6, 29): 591,    # Peter and Paul (day)
    (7, 22): 603,    # Mary Magdalene
    (7, 29): 607,    # Martha, Mary and Lazarus
    (8, 6): 614,     # The Transfiguration
    (8, 15): 622,    # The Assumption (day)
    (9, 14): 638,    # The Exaltation of the Holy Cross
    (10, 28): 666,   # Simon and Jude
    (11, 1): 667,    # All Saints
    (11, 2): 668,    # All Souls
    (11, 9): 671,    # The Dedication of the Lateran Basilica
    (12, 8): 689,    # The Immaculate Conception
}
_EPIPHANY = 20
_BAPTISM_OF_THE_LORD = 21


def easter(year):
    """Gregorian Easter (the anonymous computus)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 19 * l) // 433
    month, day = divmod(h + l - 7 * m + 90, 25)
    day = (h + l - 7 * m + 33 * month + 19) % 32
    return datetime.date(year, month, day)


def _sunday_on_or_after(date):
    return date + _DAY * ((6 - date.weekday()) % 7)


def advent_start(year):
    """First Sunday of Advent -- the Sunday on or after 27 November."""
    return _sunday_on_or_after(datetime.date(year, 11, 27))


def baptism_of_the_lord(year):
    """Sunday after Epiphany. Epiphany is kept on the Sunday between Jan 2-8
    in the United States, and the Baptism follows it."""
    epiphany = _sunday_on_or_after(datetime.date(year, 1, 2))
    following = epiphany + _DAY * 7
    # When Epiphany falls on 7 or 8 January the Baptism is the next day.
    return following if epiphany.day <= 6 else epiphany + _DAY


def cycle(date):
    """Sunday cycle A, B or C. The liturgical year begins at Advent."""
    year = date.year + (1 if date >= advent_start(date.year) else 0)
    return "ABC"[(year - 1) % 3]


def _cycle_index(date):
    return "ABC".index(cycle(date))


def _ordinal_week(date, easter_day, baptism, advent):
    """(week, weekday_index) in Ordinary Time, or None."""
    ash = easter_day - _DAY * 46
    pentecost = easter_day + _DAY * 49
    if baptism < date < ash:
        # First stretch: week 1 begins the day after the Baptism of the Lord.
        return (date - baptism).days // 7 + 1, (date.weekday()) % 7
    if pentecost < date < advent:
        # Second stretch, numbered backwards so the last week before Advent is
        # the 34th -- the weeks lost to Lent and Easter are the ones skipped.
        last_saturday = advent - _DAY
        weeks_back = (last_saturday - date).days // 7
        return 34 - weeks_back, date.weekday()
    return None


def liturgical_day(date):
    """(season, week, weekday_index) -- the coordinates a lectionary number
    encodes. weekday_index is Python's: Monday 0 .. Sunday 6."""
    easter_day = easter(date.year)
    ash = easter_day - _DAY * 46
    palm = easter_day - _DAY * 7
    pentecost = easter_day + _DAY * 49
    baptism = baptism_of_the_lord(date.year)
    advent = advent_start(date.year)

    # Christmas is tested before Advent. Advent starts in late November, so
    # "date >= advent" is true for the whole of Christmas too, and testing it
    # first made 25 December report as the fourth week of Advent -- which also
    # left the weekdays of the octave unnumbered.
    if date >= datetime.date(date.year, 12, 25) or date <= baptism:
        return "Christmas", None, date.weekday()
    if date >= advent:
        return "Advent", (date - advent).days // 7 + 1, date.weekday()
    if ash <= date < palm:
        if date < ash + _DAY * 4:
            return "AshWeek", 0, date.weekday()
        first_sunday = ash + _DAY * 4
        return "Lent", (date - first_sunday).days // 7 + 1, date.weekday()
    if palm <= date < easter_day:
        return "HolyWeek", None, date.weekday()
    if easter_day <= date <= pentecost:
        return "Easter", (date - easter_day).days // 7 + 1, date.weekday()
    ordinary = _ordinal_week(date, easter_day, baptism, advent)
    if ordinary:
        return "OT", ordinary[0], ordinary[1]
    return None, None, date.weekday()


def lectionary_number(date):
    """The lectionary number for a date, or None if this module cannot say."""
    fixed = _FIXED.get((date.month, date.day))
    season, week, weekday = liturgical_day(date)

    if weekday == 6:  # Sunday
        index = _cycle_index(date)
        easter_day = easter(date.year)
        # A fixed solemnity or feast of the Lord displaces an Ordinary Time
        # Sunday; the seasons of Advent, Lent and Easter keep their Sundays.
        if fixed and season == "OT":
            return fixed
        if date == _sunday_on_or_after(datetime.date(date.year, 1, 2)):
            return _EPIPHANY
        if date == baptism_of_the_lord(date.year):
            return _BAPTISM_OF_THE_LORD
        if date == easter_day:
            return _EASTER_SUNDAY
        if date == easter_day - _DAY * 7:
            return (37, 38, 39)[index]
        if date == easter_day + _DAY * 49:
            return _PENTECOST_DAY
        if date == easter_day + _DAY * 56:
            return _TRINITY[index]
        if date == easter_day + _DAY * 63:
            return _CORPUS_CHRISTI[index]
        if datetime.date(date.year, 12, 26) <= date <= datetime.date(date.year, 12, 31):
            return _HOLY_FAMILY
        if season == "Advent" and week in _SUNDAY_ADVENT:
            return _SUNDAY_ADVENT[week][index]
        if season == "Lent" and week in _SUNDAY_LENT:
            return _SUNDAY_LENT[week][index]
        if season == "Easter" and week in _SUNDAY_EASTER:
            return _SUNDAY_EASTER[week][index]
        if season == "OT" and week:
            # 2nd Sunday of OT is 64/65/66; each later week adds three.
            return 64 + (week - 2) * 3 + index if week >= 2 else None
        return fixed

    if fixed:
        return fixed
    weekday_christmas = _CHRISTMAS_WEEKDAYS.get((date.month, date.day))
    if weekday_christmas and season == "Christmas":
        return weekday_christmas

    if season == "AshWeek":
        return _ASH_WEDNESDAY + (date - (easter(date.year) - _DAY * 46)).days
    if season == "Lent" and week:
        monday = (_LENT_WEEK1_MONDAY if week == 1
                  else _LENT_WEEK2_MONDAY + _LENT_WEEK_STEP * (week - 2))
        return monday + weekday
    if season == "HolyWeek":
        if weekday == 3:
            return _HOLY_THURSDAY
        if weekday == 4:
            return _GOOD_FRIDAY
        if weekday == 5:
            return _EASTER_VIGIL
        return _HOLY_WEEK_MONDAY + weekday
    if season == "Easter" and week:
        if week == 1:
            return _EASTER_OCTAVE_MONDAY + weekday
        return _EASTER_WEEK2_MONDAY + 6 * (week - 2) + weekday
    if season == "OT" and week:
        return _OT_WEEK1_MONDAY + 6 * (week - 1) + weekday
    if season == "Advent" and week and week <= 3 and date.day < 17:
        return _ADVENT_WEEK1_MONDAY + 6 * (week - 1) + weekday
    return None


def ferial_year(date):
    """Year I or II, which picks the first reading on Ordinary Time weekdays.

    Odd liturgical years are Year I. The liturgical year begins at Advent, so
    December of 2026 already belongs to 2027."""
    year = date.year + (1 if date >= advent_start(date.year) else 0)
    return "I" if year % 2 else "II"


_SEASON_NAMES = {"OT": "OT", "Lent": "Lent", "Easter": "Easter",
                 "Advent": "Advent", "Christmas": "Christmas"}
# Taken from homilist rather than restated: describe() and standardize_day were
# writing different abbreviations for the same weekday.
_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def describe(date):
    """A short human name for a date, in the archive's own day form."""
    season, week, weekday = liturgical_day(date)
    day = _WEEKDAYS[weekday]
    if season in _SEASON_NAMES and week:
        suffix = ("th" if 11 <= week % 100 <= 13
                  else {1: "st", 2: "nd", 3: "rd"}.get(week % 10, "th"))
        return f"{day} {week}{suffix} of {_SEASON_NAMES[season]}"
    if season == "HolyWeek":
        return f"{day} of Holy Week"
    if season == "Christmas" and date.month == 12 and date.day >= 25:
        # 25 December is Christmas; 26-31 are numbered days of its octave.
        if date.day == 25:
            return "Christmas"
        n = date.day - 24
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix} Day in the Octave of Christmas"
    if season == "AshWeek":
        return "Ash Wednesday" if weekday == 2 else f"{day} after Ash Wednesday"
    return f"{day} {date.isoformat()}"


def dates_for_lectionary(number, around, radius=32):
    """Dates near `around` carrying `number`, nearest first.

    Same shape as the USCCB lookup it replaces: the file's modified timestamp
    gives a window (within 30 days in every measured case) and the number picks
    the day inside it. Unlike the lookup, a wrong answer here is a bug that the
    tests can catch rather than a silent 403.
    """
    if number is None or around is None:
        return []
    out = []
    for offset in range(radius + 1):
        for delta in ((0,) if offset == 0 else (offset, -offset)):
            candidate = around + datetime.timedelta(days=delta)
            if lectionary_number(candidate) == number:
                out.append(candidate)
    return out

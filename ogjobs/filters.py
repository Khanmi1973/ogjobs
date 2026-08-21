"""Relevance filtering and scoring.

Turns a raw scrape into a ranked shortlist: geography first (GCC + Africa),
then discipline keywords, then freshness.
"""
import re
from datetime import datetime, timezone

from . import geo


class Filters:
    def __init__(self, cfg):
        self.cfg = cfg or {}
        c = self.cfg.get("countries", {})
        self.include_countries = {x for x in (c.get("include") or []) if not x.startswith("_")}
        self.include_regions = {x for x in (c.get("regions") or []) if not x.startswith("_")}
        self.allow_unknown = bool(c.get("allow_unknown_location", False))
        self.allow_remote = bool(c.get("allow_remote", True))

        r = self.cfg.get("roles", {})
        self.must_any = [t.lower() for t in (r.get("must_any") or []) if not t.startswith("_")]
        self.exclude = [t.lower() for t in (r.get("exclude") or []) if not t.startswith("_")]
        # Keys beginning with "_" are documentation comments in the JSON, not data.
        self.boost = {k.lower(): int(v) for k, v in (r.get("boost") or {}).items()
                      if not k.startswith("_") and isinstance(v, (int, float))}
        self.min_score = int(self.cfg.get("min_score", 0))
        self.max_age_days = int(self.cfg.get("max_age_days", 0))

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def _has(term, text):
        if not term or not text:
            return False
        if re.search(r"[^a-z0-9 ]", term):        # phrase with punctuation
            return term in text
        return re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(term), text) is not None

    def annotate(self, job):
        """Attach geography metadata in place.

        The stated location wins outright. Only when a job gives us no usable
        location do we fall back to the title and description - otherwise an
        advert based in Athens that merely mentions Angola in its blurb would
        look like an Angolan job.
        """
        loc_countries, loc_regions, loc_flags = geo.detect(job.location)
        if loc_countries:
            job.countries, job.regions, job.flags = loc_countries, loc_regions, loc_flags
            return job

        # A location that clearly names somewhere else settles it too.
        if job.location and geo.detect_other(job.location):
            job.countries, job.regions = [], []
            job.flags = loc_flags
            return job

        countries, regions, flags = geo.detect(job.location, job.title,
                                               job.description[:1500], job.url)
        job.countries, job.regions, job.flags = countries, regions, flags
        return job

    # ---- main ----------------------------------------------------------

    def evaluate(self, job):
        """Return (keep: bool, reason: str). Sets job.score and job.matched."""
        self.annotate(job)
        title = (job.title or "").lower()
        desc = (job.description or "").lower()
        blob = title + " \n " + desc

        for term in self.exclude:
            if self._has(term, title) or self._has(term, desc[:2500]):
                return False, "excluded term: %s" % term

        score, matched = 0, []

        # --- geography ---
        geo_ok = False
        hit_countries = [c for c in job.countries if not self.include_countries
                         or c in self.include_countries]
        if hit_countries:
            score += 40
            matched.extend(hit_countries)
            geo_ok = True
        elif self.include_regions and set(job.regions) & self.include_regions:
            score += 18
            matched.extend(sorted(set(job.regions) & self.include_regions))
            geo_ok = True
        elif ("remote" in job.flags and self.allow_remote
              and not geo.detect_other(job.location, job.title)):
            score += 8
            matched.append("remote")
            geo_ok = True
        elif not job.location and self.allow_unknown:
            score += 2
            geo_ok = True

        if not geo_ok:
            return False, "outside target geography"

        # --- discipline keywords ---
        if self.must_any:
            in_title = [t for t in self.must_any if self._has(t, title)]
            in_desc = [t for t in self.must_any if self._has(t, desc)]
            if in_title:
                score += 30
                matched.extend(in_title[:4])
            elif in_desc:
                score += 12
                matched.extend(in_desc[:3])
            else:
                return False, "no matching role keyword"

        for term, weight in self.boost.items():
            if self._has(term, blob):
                score += weight
                if weight > 0:
                    matched.append(term)

        if "rotational" in job.flags:
            score += 6
            matched.append("rotational")

        # --- freshness ---
        if job.posted:
            try:
                d = datetime.strptime(job.posted, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - d).days
                if self.max_age_days and age > self.max_age_days:
                    return False, "older than %d days" % self.max_age_days
                if age <= 3:
                    score += 12
                elif age <= 7:
                    score += 8
                elif age <= 21:
                    score += 4
            except Exception:
                pass

        job.score = score
        seen, uniq = set(), []
        for m in matched:
            k = m.lower()
            if k not in seen:
                seen.add(k)
                uniq.append(m)
        job.matched = uniq[:10]

        if score < self.min_score:
            return False, "score %d below minimum %d" % (score, self.min_score)
        return True, "ok"

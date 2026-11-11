import re

DIRECT_LABEL = "direct"
PROFILE_FIELDS = ("delay_ms", "jitter_ms", "loss", "reorder")


class NetworkProfile:
    def __init__(self, delay_ms=0.0, jitter_ms=0.0, loss=0.0, reorder=0.0, repeat=None):
        self.repeat = repeat
        self.delay_ms = float(delay_ms)
        self.jitter_ms = float(jitter_ms)
        self.loss = float(loss)
        self.reorder = float(reorder)
        if min(self.delay_ms, self.jitter_ms, self.loss, self.reorder) < 0:
            raise ValueError("network values must not be negative")
        if self.loss > 1 or self.reorder > 1:
            raise ValueError("loss and reorder are probabilities between 0 and 1")

    def key(self):
        return (self.delay_ms, self.jitter_ms, self.loss, self.reorder)

    def label(self):
        text = "d%g-j%g" % (self.delay_ms, self.jitter_ms)
        if self.loss:
            text += "-l%g" % self.loss
        if self.reorder:
            text += "-r%g" % self.reorder
        return text

    def as_dict(self):
        return dict(zip(PROFILE_FIELDS, self.key()))

    def spec(self):
        text = ":".join("%g" % value for value in self.key())
        return text if self.repeat is None else "%s@%d" % (text, self.repeat)


DIRECT = NetworkProfile()


def parse_profile(text):
    if text in (None, "", DIRECT_LABEL):
        return NetworkProfile()
    numbers, _, repeat = text.partition("@")
    count = int(repeat) if repeat else None
    if count is not None and count < 1:
        raise ValueError("a profile repeat must be at least 1: %r" % text)
    return NetworkProfile(*[float(part) if part else 0.0 for part in numbers.split(":")], repeat=count)


def parse_profiles(texts):
    profiles = []
    seen = set()
    for text in texts or [DIRECT_LABEL]:
        profile = parse_profile(text)
        if profile.key() not in seen:
            seen.add(profile.key())
            profiles.append(profile)
    return profiles


class Launch:
    def __init__(self, number, build, startup_group, profiles, repetitions, match):
        self.number = number
        self.build = build
        self.startup_group = startup_group
        self.profiles = profiles
        self.repetitions = repetitions
        self.match = match

    @property
    def identifier(self):
        return "L%d-%s-%s" % (self.number, re.sub(r"[^A-Za-z0-9.-]", "", self.build), self.startup_group)

    def arguments(self):
        arguments = ["--together", self.build, "--repeat", str(self.repetitions), "--launch-id", self.identifier,
                     "--group", self.startup_group, "--net"] + [profile.spec() for profile in self.profiles]
        if self.match:
            arguments += ["--match"] + list(self.match)
        return arguments


def plan_launches(builds, startup_groups, profiles, repetitions=1, match=None):
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    launches = []
    seen = set()
    for build in builds:
        for group in startup_groups:
            if (build, group) in seen:
                continue
            seen.add((build, group))
            launches.append(Launch(len(launches) + 1, build, group, profiles, repetitions, match))
    return launches


def runs_in_launch(launch, counts):
    steady = counts.get(launch.startup_group, {"plain": 0, "network": 0})
    network_runs = sum(profile.repeat or launch.repetitions for profile in launch.profiles) * steady["network"]
    return steady["plain"] * launch.repetitions + network_runs


def describe_launches(launches, counts):
    lines = ["launches (%d):" % len(launches)]
    for launch in launches:
        lines.append("  %-34s build %-14s group %-17s %d scenario runs, networks %s" % (
            launch.identifier, launch.build, launch.startup_group, runs_in_launch(launch, counts), ", ".join(p.label() for p in launch.profiles)))
    return lines


def launches_without_grouping(launches, counts):
    return sum(runs_in_launch(launch, counts) for launch in launches)

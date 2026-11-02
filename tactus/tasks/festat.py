"""Festat task — B matrix statistics (stabal96.*) from ensemble forecasts."""

import os

from ..datetime_utils import as_datetime, as_timedelta
from ..eps.eps_setup import get_member_config
from ..logs import logger
from ..namelist import NamelistGenerator, write_namelist
from ..os_utils import tactusmakedirs
from ..suites.suite_utils import Cycles
from ..toolbox import Platform
from .base import Task
from .batch import BatchJob

# Files written by FESTAT (NAMFESTAT OUTBAL, OUTCVU, OUTCVT), as read by OopsVar
_OUTPUT_FILES = ["stabal96.bal", "stabal96.cv", "stabal96.cvt"]


def festat_cases(config, members, lead_time):
    """Return the forecast files used by FESTAT, grouped by cycle.

    Args:
        config (ParsedConfig): Configuration
        members (list): Ensemble members to use
        lead_time (datetime.timedelta): Forecast lead time of the used files

    Returns:
        list: One list of archived history files per cycle, ordered by member.

    """
    cycles = Cycles(
        first_cycle=config["general.times.start"],
        last_cycle=config["general.times.end"],
        cycle_length=config["general.times.cycle_length"],
    )
    platforms = [Platform(get_member_config(config, member=m)) for m in members]
    groups = []
    for cycle in cycles:
        basetime = as_datetime(cycle.basetime)
        groups.append([
            platform.substitute(
                "@ARCHIVE@/@HISTORY_TEMPLATE@",
                basetime=basetime,
                validtime=basetime + lead_time,
            )
            for platform in platforms
        ])
    return groups


class Festat(Task):
    """Compute the B matrix statistics with FESTAT from ensemble forecasts.

    FESTAT reads the forecasts (FA) directly as ensdiff001..ensdiffNNN and
    builds the differences itself, between consecutive members of each group.
    A group is one cycle, so the differences are between members valid at the
    same time. The resulting stabal96.* files go to ``bmatrix.outdir``.
    """

    def __init__(self, config):
        """Construct Festat task.

        Args:
            config (ParsedConfig): Configuration

        """
        Task.__init__(self, config, __class__.__name__)
        self.members = list(config.get("bmatrix.members", config["eps.general.members"]))
        self.lead_time = as_timedelta(
            config.get("bmatrix.lead_time", config["general.times.forecast_range"])
        )
        self.outdir = config["bmatrix.outdir"]
        logger.debug("Constructed Festat task")

    def execute(self):
        """Run FESTAT and archive the B matrix files."""
        # SUFESTAT aborts on groups of less than 3 members
        if len(self.members) < 3:
            raise RuntimeError(
                f"Festat: needs at least three members, got {self.members}"
            )

        festat = self.get_binary("FESTAT")
        self.fmanager.input(festat, "FESTAT")

        # --- input forecasts: ensdiffNNN, ordered by cycle, then member ---
        groups = festat_cases(self.config, self.members, self.lead_time)
        ncases = 0
        for group in groups:
            for filename in group:
                ncases += 1
                self.fmanager.input(filename, f"ensdiff{ncases:03d}")
        logger.info(
            "Festat: {} cases, {} cycles x {} members, lead time {}",
            ncases,
            len(groups),
            len(self.members),
            self.lead_time,
        )

        # --- namelist ---
        nlgen = NamelistGenerator(self.config, "festat")
        nlgen.load("festat")
        nml = nlgen.assemble_namelist("festat")
        nml["NAMFESTAT"]["NCASES"] = ncases
        # NGRPTS(0) is the number of groups, NGRPTS(i) the members in group i
        nml["NAMFESTAT"]["NGRPTS"] = [len(groups)] + [len(g) for g in groups]
        write_namelist(nml, "fort.4")

        # --- run FESTAT ---
        # Without DR_HOOK_NOT_MPI, FESTAT does not initialise MPI itself
        rte = {**os.environ, "DR_HOOK_NOT_MPI": "1"}
        BatchJob(rte, wrapper=self.platform.substitute(self.wrapper)).run("./FESTAT")

        # --- archive output ---
        outdir = self.platform.substitute(self.outdir)
        tactusmakedirs(outdir)
        for fname in _OUTPUT_FILES:
            if not os.path.isfile(fname) or os.path.getsize(fname) == 0:
                raise RuntimeError(f"Festat: {fname} not produced or empty.")
            self.fmanager.output(fname, os.path.join(outdir, fname), provider_id="copy")
        logger.info("Festat: B matrix files archived to {}", outdir)
        self.archive_logs(["fort.4"])

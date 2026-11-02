"""Ecflow suite computing a B matrix from an ensemble (e.g. a downscaling one)."""

from tactus.suites.base import EcflowSuiteTask, EcflowSuiteTrigger, EcflowSuiteTriggers
from tactus.suites.suite_utils import Cycles
from tactus.suites.tactus import TactusSuiteDefinition


class BMatrixSuiteDefinition(TactusSuiteDefinition):
    """The tactus suite for the ensemble, followed by Festat.

    The ensemble itself is configured as usual (eps.general.members, and for a
    downscaling suite_control.mode = "cold_start" without data assimilation).
    Festat runs once all cycles are complete and uses every member of every cycle.
    """

    def add_final_nodes(self, config, input_template, trigger):
        """Add the Festat task after all cycles.

        Args:
            config (ParsedConfig): Configuration file
            input_template (str): ecFlow job template
            trigger (list): Nodes Festat triggers on, besides the cycles

        Returns:
            list: The Festat task.

        """
        if not config["suite_control.create_time_dependent_suite"]:
            return []

        # Wait for all days, not only the last cycle: Festat reads the
        # forecasts of every cycle.
        cycles = Cycles(
            first_cycle=config["general.times.start"],
            last_cycle=config["general.times.end"],
            cycle_length=config["general.times.cycle_length"],
        )
        days = sorted({cycle.day for cycle in cycles})
        # trigger holds at least the last time family of the suite
        festat_trigger = EcflowSuiteTriggers([
            EcflowSuiteTrigger(node) for node in trigger
        ])
        days_string = " AND ".join(f"{self.suite.path}/{day} == complete" for day in days)
        festat_trigger.trigger_string += f" AND ({days_string})"

        festat = EcflowSuiteTask(
            "Festat",
            self.suite,
            config,
            self.task_settings,
            self.ecf_files,
            input_template=input_template,
            trigger=festat_trigger,
            ecf_files_remotely=self.ecf_files_remotely,
        )
        return [festat]

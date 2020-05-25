from importlib.util import find_spec
import time
from logging import getLogger
from pprint import pformat
from pathlib import Path
import tempfile
from typing import Any, Callable, Dict  # NOQA

from kedro.pipeline.node import Node  # NOQA

log = getLogger(__name__)


try:
    from kedro.framework.hooks import hook_impl
except ModuleNotFoundError:

    def hook_impl(func):
        return func


def _get_metric_name(node: Node) -> str:
    func_name = (
        node._func_name.replace("<", "")
        .replace(">", "")
        .split(" ")[0]
        .split(".")[-1][:250]
    )
    return "_time_to_run {} -- {}".format(func_name, " - ".join(node.outputs))


class MLflowTimeLoggerHook:
    """
    Log duration time to run each node (task).
    Optionally, the gantt chart html is generated by `plotly.figure_factory.create_gantt`
    (https://plotly.github.io/plotly.py-docs/generated/plotly.figure_factory.create_gantt.html)
    Optionally, the metrics and gantt chart image can be logged to MLflow.
    """

    _time_begin_dict = {}
    _time_end_dict = {}
    _time_dict = {}

    def __init__(
        self,
        enable_mlflow: bool = True,
        enable_plotly: bool = True,
        gantt_filepath: str = None,
        gantt_params: Dict[str, Any] = {},
        metric_name_func: Callable[[Node], str] = _get_metric_name,
    ):
        """
        Args:
            enable_mlflow: Enable logging to MLflow.
            enable_plotly: Enable visualization of logged time as a gantt chart.
            gantt_filepath: File path to save the generated gantt chart.
            gantt_params: Args fed to:
                https://plotly.github.io/plotly.py-docs/generated/plotly.figure_factory.create_gantt.html
            metric_name_func: Callable to return the metric name using ``kedro.pipeline.node.Node``
                object.
        """
        self.enable_mlflow = find_spec("mlflow") and enable_mlflow
        self.enable_plotly = find_spec("plotly") and enable_plotly
        self.gantt_filepath = gantt_filepath
        self.gantt_params = gantt_params
        self._metric_name_func = metric_name_func

    @hook_impl
    def before_node_run(self, node, catalog, inputs):
        node_name = self._metric_name_func(node)
        time_begin_dict = {node_name: time.time()}
        self._time_begin_dict.update(time_begin_dict)

    @hook_impl
    def after_node_run(self, node, catalog, inputs, outputs):
        node_name = self._metric_name_func(node)
        time_end_dict = {node_name: time.time()}
        self._time_end_dict.update(time_end_dict)

        time_dict = {
            node_name: (
                self._time_end_dict.get(node_name)
                - self._time_begin_dict.get(node_name)
            )
        }

        log.info("Time duration: {}".format(time_dict))

        if self.enable_mlflow:

            from mlflow import log_metrics

            log_metrics(time_dict)

        self._time_dict.update(time_dict)

    @hook_impl
    def after_pipeline_run(self, run_params, pipeline, catalog):
        log.info("Time duration: \n{}".format(pformat(self._time_dict)))

        if self.enable_plotly and self._time_begin_dict:

            from plotly.figure_factory import create_gantt

            df = [
                dict(
                    Task=k,
                    Start=self._time_begin_dict.get(k) * 1000,
                    Finish=self._time_end_dict.get(k) * 1000,
                )
                for k in self._time_begin_dict.keys()
            ]

            fig = create_gantt(df, **self.gantt_params)

            fp = self.gantt_filepath or (tempfile.gettempdir() + "/_gantt.html")
            Path(fp).parent.mkdir(parents=True, exist_ok=True)
            fig.write_html(fp)

            if self.enable_mlflow:

                from mlflow import log_artifact

                log_artifact(fp)

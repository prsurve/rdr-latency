# -*- coding: utf8 -*-

# Copyright 2021 Martin Bukatovič <mbukatov@redhat.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import logging
import subprocess

import yaml


LOGGER = logging.getLogger(name=__file__)


def run_oc(cmd_list, kubeconfig=None, oc_executable=None, timeout=600):
    """
    Run given oc command and log all it's output.

    Args:
        cmd_list (list): oc command to run, eg. ``["get", "nodes"]`` will
            execute ``oc get nodes`` process
        timeout (int): command timeout specified in seconds, optional
        kubeconfig (str): file path to kubeconfig (optional, use only if you
            need to override the default)
        oc_executable (str): file path of oc command (optional, use only if
            you need to override the default)

    Returns:
        tuple: stdout, stderr of the command executed
    """
    if oc_executable is None:
        oc_executable = "oc"
    oc_cmd = [oc_executable]
    if kubeconfig is not None:
        oc_cmd.extend(["--kubeconfig", kubeconfig])
    oc_cmd.extend(cmd_list)
    LOGGER.info("going to execute %s", oc_cmd)
    comp_proc = subprocess.run(oc_cmd, capture_output=True, timeout=timeout)
    # log whole output of the process
    proc_log_level = logging.DEBUG
    if comp_proc.returncode > 0:
        proc_log_level = logging.WARNING
    LOGGER.log(proc_log_level, "oc stdout: %s", comp_proc.stdout)
    LOGGER.log(proc_log_level, "oc stderr: %s", comp_proc.stderr)
    LOGGER.log(proc_log_level, "oc return code: %d", comp_proc.returncode)
    # after the logging is done, we can raise the exception if necessary
    comp_proc.check_returncode()
    # if all is ok, let's return output
    stdout = comp_proc.stdout.decode()
    stderr = comp_proc.stderr.decode()
    return stdout, stderr

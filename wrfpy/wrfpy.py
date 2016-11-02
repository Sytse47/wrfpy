#!/usr/bin/env python

'''
description:    Configuration part of wrfpy
license:        APACHE 2.0
author:         Ronald van Haren, NLeSC (r.vanharen@esciencecenter.nl)
'''

from config import config
import utils
import os
import argparse

class wrfpy(config):
  def __init__(self):
    results = self._cli_parser()
    global logger
    logger = utils.start_logging(os.path.join(os.path.expanduser("~"),
                                              'wrfpy.log'))
    if results['init']:
      self._create_directory_structure(results['suitename'],
                                        results['basedir'])
    elif results['create']:
      self._create_cylc_config(results['suitename'],
                               results['basedir'])


  def _cli_parser(self):
    '''
    parse command line arguments
    '''
    parser = argparse.ArgumentParser(
      description='WRFpy',
      formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--init', action='store_true',
                        help='Initialize suite')
    parser.add_argument('--create', action='store_true',
                        help='Create suite config')
    parser.add_argument('--basedir', type=str,
                        default=os.path.join(os.path.expanduser("~"),
                        'cylc-suites'),
                        help="basedir in which suites are installed")
    parser.add_argument('--suitename', type=str, required=True,
                         help='name')
    results = vars(parser.parse_args())
    # either initialize or create a suite, not both
    if (results['init'] ^ results['create']):
      return results
    else:
      # print error message to the user, combiniation of --init and --create
      # is not allowed
      print("Only one of '--init' and '--create' is allowed.")
      exit()


  def _create_directory_structure(self, suitename, basedir=None):
    '''
    Create directory structure for the Cylc configuration
    '''
    # set basedir to users home directory if not supplied
    if not basedir:
      basedir = os.path.join(os.path.expanduser("~"), 'cylc-suites')
    # subdirectories to create
    subdirs = ['bin' , 'control', 'doc', 'inc']
    # create subdirectories
    [utils._create_directory(
     os.path.join(basedir, suitename, subdir))
     for subdir in subdirs]
    # create empty json config file in suite directory
    # this does not overwrite an existing config file
    config.__init__(self, os.path.join(
                    basedir, suitename, 'config.json'))


  def _create_cylc_config(self, suitename, basedir):
    '''
    Create cylc suite.rc configuration file based on config.json
    '''
    config.__init__(self, os.path.join(
                    basedir, suitename, 'config.json'))
    suiterc = self._header()
    suiterc += self._scheduling()
    suiterc += self._runtime()
    suiterc += self._visualization()
    self._write(suiterc, os.path.join(basedir, suitename, 'suite.rc'))


  def _header(self):
    '''
    define suite.rc header information
    '''
    start_time = utils.datetime_to_string(
      utils.return_validate(self.config['options_general']['date_start']),
      format='%Y%m%d%H')
    end_time = utils.datetime_to_string(
      utils.return_validate(self.config['options_general']['date_end']),
      format='%Y%m%d%H')
    # define template
    template = """#!Jinja2

{{% set START = "{start_time}" %}}
{{% set STOP  = "{end_time}" %}}

[cylc]
  # set required cylce point format
  cycle point format = %Y%m%d%H

"""
    # context variables in template
    context = {
      "start_time":start_time,
      "end_time":end_time
      }
    return template.format(**context)

  def _scheduling(self):
    '''
    define suite.rc scheduling information
    '''
    # get start_hour and increment time from config.json
    start_hour = str(
      utils.return_validate(
      self.config['options_general']['date_start']).hour).zfill(2)
    incr_hour = self.config['options_general']['run_hours']
    # define template
    template = """[scheduling]
  initial cycle point = {{{{ START }}}}
  final cycle time   = {{{{ STOP }}}}
  [[dependencies]]
    # Initial cycle point
    [[[R1/T{start_hour}]]]
      graph = \"\"\"
        wrf_init => wrf_real => wrfda => wrf_run
        wrf_init => obsproc_init => obsproc_run
        obsproc_run => wrfda
      \"\"\"
    # Repeat every {incr_hour} hours, starting {incr_hour} hours after initial cylce point
    [[[+PT{incr_hour}H/PT{incr_hour}H]]]
      graph = \"\"\"
        wrf_run[-PT2H] => wrf_init => wrf_real => wrfda => copy_urb => wrf_run
        wrf_init => obsproc_init => obsproc_run
        obsproc_run => wrfda
      \"\"\"

"""
    # context variables in template
    context = {
      "start_hour": start_hour,
      "incr_hour": incr_hour
      }
    return template.format(**context)


  def _runtime(self):
    '''
    define suite.rc runtime information
    '''
    return (self._runtime_base() + self._runtime_init() + self._runtime_real() +
            self._runtime_wrf() + self._runtime_obsproc() +
            self._runtime_wrfda())


  def _runtime_base(self):
    '''
    define suite.rc runtime information: base
    '''
    # define template
    template = """[runtime]
  [[root]] # suite defaults
    [[[job submission]]]
      method = background
"""
    # context variables in template
    context = {}
    return template.format(**context)


  def _runtime_init(self):
    '''
    define suite.rc runtime information: init
    '''
    wrf_init_command = "wrf_init.py $CYLC_TASK_CYCLE_POINT"
    obsproc_init_command = "wrfda_obsproc_init.py $CYLC_TASK_CYCLE_POINT"
    # defne template
    template = """
  [[init]]
    script = \"\"\"
{wrf_init}
{obsproc_init}
\"\"\"
"""
    # context variables in template
    context = {
      "wrf_init": wrf_init_command,
      "obsproc_init":  obsproc_init_command
      }
    return template.format(**context)


  def _runtime_real(self):
    '''
    define suite.rc runtime information: real.exe
    '''
    # define template
    template = """
  [[wrf_real]]
    script = \"\"\"
#!/usr/bin/env bash
if [ -n "$SLURM_CPUS_PER_TASK" ]; then
  omp_threads=$SLURM_CPUS_PER_TASK
else
  omp_threads=1
fi
export OMP_NUM_THREADS=$omp_threads
srun ./real.exe
\"\"\"
    [[[environment]]]
      WORKDIR = {wrf_run_dir}
      CYLC_TASK_WORK_DIR = $WORKDIR
    [[[job submission]]]
      method = {method}
    [[[directives]]]
      {directives}
"""
    if self.config['options_slurm']['slurm_real.exe']:
      method = "slurm"
      with open(self.config['options_slurm']['slurm_real.exe'], 'r') as myfile:
        directives=myfile.read().replace('\n', '\n      ')
    else:
        method = "background"
        directives=""
    # context variables in template
    context = {
      "wrf_run_dir": self.config['filesystem']['wrf_run_dir'],
      "method": method,
      "directives": directives
      }
    return template.format(**context)


  def _runtime_wrf(self):
    '''
    define suite.rc runtime information: wrf.exe
    '''
    # define template
    template = """
  [[wrf_run]]
    script = \"\"\"
#!/usr/bin/env bash
if [ -n "$SLURM_CPUS_PER_TASK" ]; then
  omp_threads=$SLURM_CPUS_PER_TASK
else
  omp_threads=1
fi
export OMP_NUM_THREADS=$omp_threads
srun ./wrf.exe
\"\"\"
    [[[environment]]]
      WORKDIR = {wrf_run_dir}
      CYLC_TASK_WORK_DIR = $WORKDIR
    [[[job submission]]]
      method = {method}
    [[[directives]]]
      {directives}
"""
    if self.config['options_slurm']['slurm_wrf.exe']:
      method = "slurm"
      with open(self.config['options_slurm']['slurm_wrf.exe'], 'r') as myfile:
        directives=myfile.read().replace('\n', '\n      ')
    else:
        method = "background"
        directives=""
    # context variables in template
    context = {
      "wrf_run_dir": self.config['filesystem']['wrf_run_dir'],
      "method": method,
      "directives": directives
      }
    return template.format(**context)


  def _runtime_obsproc(self):
    '''
    define suite.rc runtime information: obsproc.exe
    '''
    # define template
    template = """
  [[obsproc_run]]
    script = \"\"\"
#!/usr/bin/env bash
srun ./obsproc.exe
\"\"\"
    [[[environment]]]
      WORKDIR = {obsproc_dir}
      CYLC_TASK_WORK_DIR = $WORKDIR
    [[[job submission]]]
      method = {method}
    [[[directives]]]
      {directives}
"""
    if self.config['options_slurm']['slurm_obsproc.exe']:
      method="slurm"
      with open(self.config[
                'options_slurm']['slurm_obsproc.exe'], 'r') as myfile:
        directives=myfile.read().replace('\n', '\n      ')
    else:
        method = "background"
        directives=""
    # context variables in template
    context = {
      "obsproc_dir": os.path.join(self.config['filesystem']['work_dir'], 'obsproc'),
      "method": method,
      "directives": directives
      }
    return template.format(**context)


  def _runtime_wrfda(self):
    '''
    define suite.rc runtime information: wrfda
    '''
    # define template
    template = """
  [[wrfda]]
    script = wrfda_run.py $CYLC_TASK_CYCLE_POINT
"""
    # context variables in template
    context = {}
    return template.format(**context)


  def _visualization(self):
    '''
    define suite.rc visualization information
    '''
    # define template
    template = """
[visualization]
  initial cycle point = {{ START }}
  final cycle time   = {{ STOP }}
  default node attributes = "style=filled", "fillcolor=grey"
"""
    return template


  def _write(self, suiterc, filename):
    '''
    write cylc suite.rc config to file
    '''
    # create the itag file and write content to it based on the template
    try:
      with open(filename, 'w') as itag:
        itag.write(suiterc)
    except IOError as e:
      #logger.error('Unable to write itag file: %s' %filename)
      raise  # re-raise exception
    #logger.debug('Leave write_itag')


if __name__ == "__main__":
  wrfpy()

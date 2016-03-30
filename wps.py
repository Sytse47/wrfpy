#!/usr/bin/env python

'''
description:    WRF Preprocessing System (WPS) part of wrfpy
license:        APACHE 2.0
author:         Ronald van Haren, NLeSC (r.vanharen@esciencecenter.nl)
'''

import utils
import glob
import subprocess
import os
import errno
import f90nml
from config import config
from datetime import datetime
import shutil

class wps(config):
  '''
  description
  '''
  def __init__(self, boundary_dir, datestart, dateend):
    config.__init__(self)  # load config
    # define and create wps working directory
    self.wps_workdir = os.path.join(self.config['filesystem']['work_dir'],
                                    'wps')
    utils._create_directory(self.wps_workdir)
    '''boundary_dir as an argument so we switch between boundary_dir and
       upp_archive_dir defined in config module'''
    self.boundary_dir = boundary_dir
    self._clean_boundaries_wps()  # clean leftover boundaries
    self._prepare_namelist(datestart, dateend)
    self._link_boundary_files()
    self._run_geogrid()
    self._link_vtable()
    self._run_ungrib()
    self._run_metgrid()


  def _clean_boundaries_wps(self):
    '''
    clean old leftover boundary files in WPS directory
    '''
    # create list of files to remove
    files = [glob.glob(os.path.join(self.wps_workdir, ext))
             for ext in ['GRIBFILE.*', 'FILE:', 'PFILE:', 'PRES:']]
    # flatten list
    files_flat = [item for sublist in files for item in sublist]
    # remove files silently
    [ utils.silentremove(filename) for filename in files_flat ]


  def _prepare_namelist(self, datestart, dateend):
    '''
    prepare wps namelist
    '''
    # read WPS namelist in WPS work_dir
    wps_nml = f90nml.read(os.path.join(self.config['filesystem']['work_dir'],
                                       'wps', 'namelist.wps'))
    # get numer of domains
    ndoms = wps_nml['share']['max_dom']
    # check if ndoms is an integer and >0
    if not (isinstance(ndoms, int) and ndoms>0):
      raise ValueError("'domains_max_dom' namelist variable should be an " \
                      "integer>0")
    # check if both datestart and dateend are a datetime instance
    if not all([ isinstance(dt, datetime) for dt in [datestart, dateend] ]):
      raise TypeError("datestart and dateend must be an instance of datetime")
    # set new datestart and dateend
    wps_nml['share']['start_date'] = [datetime.strftime(datestart,
                                                          '%Y-%m-%d_%H:%M:%S')] * ndoms
    wps_nml['share']['end_date'] = [datetime.strftime(dateend,
                                                        '%Y-%m-%d_%H:%M:%S')] * ndoms
    # write namelist in wps work_dir
    utils.silentremove(os.path.join(
      self.config['filesystem']['work_dir'], 'wps', 'namelist.wps'))
    wps_nml.write(os.path.join(
      self.config['filesystem']['work_dir'], 'wps', 'namelist.wps'))

  def _link_boundary_files(self):
    '''
    link boundary grib files to wps work directory with the required naming
    '''
    # get list of files to link
    filelist = glob.glob(os.path.join(self.boundary_dir, '*'))
    # make sure we only have files
    filelist = [fl for fl in filelist if os.path.isfile(fl)]
    if len(filelist) == 0:
      message = 'linking boundary files failed, no files found to link'
      logger.error(message)
      raise IOError(message)
    # get list of filename extensions to use for destination link
    linkext = self._get_ext_list(len(filelist))
    # link grib files
    [os.symlink(filelist[idx], os.path.join(
      self.wps_workdir, 'GRIBFILE.' + linkext[idx])) for idx in range(len(filelist))]


  def _get_ext_list(self, num):
    '''
    create list of filename extensions for num number of files
    Extensions have the form: AAA, AAB, AAC... ABA, ABB...,BAA, BAB...
    '''
    from string import ascii_uppercase
    # create list of uppercase letters used linkname extension
    ext = [ascii_uppercase[idx] for idx in range(0,len(ascii_uppercase))]
    i1, i2, i3 = 0, 0, 0
    for filenum in range(num):  # loop over number of files
      # append extension to list (or create list for first iteration)
      try:
        list_ext.append(ext[i3] + ext[i2] + ext[i1])
      except NameError:
        list_ext = [ext[i3] + ext[i2] + ext[i1]]
      i1 += 1  # increment i1
      if i1 >= len(ascii_uppercase):
        i1 = 1
        i2 += 1  # increment i2
        if i2 >= len(ascii_uppercase):
          i2 = 1
          i3 += 1  # increment i3
          if i3 >= len(ascii_uppercase):
            message = 'Too many files to link'
            logger.error(message)
            raise IOError(message)
    return list_ext


  def _link_vtable(self):
    '''
    link the required Vtable
    '''
    utils.silentremove(os.path.join(self.wps_workdir, 'Vtable'))
    # TODO: make vtable depend on the boundary source
    vtable =  'Vtable.GFS'
    vtable_path = os.path.join(self.config['filesystem']['wps_dir'], 'ungrib',
                          'Variable_Tables', vtable)
    os.symlink(vtable_path, os.path.join(self.wps_workdir, 'Vtable'))


  def _link_tbl_files(self):
    '''
    link GEOGRID.TBL and METGRID.TBL into wps work_dir
    '''
    # geogrid
    if not os.path.isfile(os.path.join(self.wps_workdir, 'geogrid',
                                       'GEOGRID.TBL')):
      geogridtbl = os.path.join(self.config['filesystem']['wps_dir'], 'geogrid',
                                'GEOGRID.TBL.ARW')
      utils._create_directory(os.path.join(self.wps_workdir, 'geogrid'))
      os.symlink(geogridtbl, os.path.join(self.wps_workdir, 'geogrid',
                                          'GEOGRID.TBL'))
    # metgrid
    if not os.path.isfile(os.path.join(self.wps_workdir, 'metgrid',
                                       'METGRID.TBL')):
      metgridtbl = os.path.join(self.config['filesystem']['wps_dir'], 'metgrid',
                                'METGRID.TBL.ARW')
      utils._create_directory(os.path.join(self.wps_workdir, 'metgrid'))
      os.symlink(metgridtbl, os.path.join(self.wps_workdir, 'metgrid',
                                          'METGRID.TBL'))


  def _run_geogrid(self):
    '''
    run geogrid.exe (locally or using slurm script defined in config.json)
    '''
    if len(self.config['options_slurm']['slurm_geogrid.exe']):
      geogrid_slurm = self.config['slurm']['slurm_geogrid.exe']
      utils.check_file_exists(geogrid_slurm)
      geogrid_command = 'sbatch ' + geogrid_slurm
    else:
      geogrid_command = os.path.join(self.config['filesystem']['wps_dir'],
                                    'geogrid', 'geogrid.exe')
      utils.check_file_exists(geogrid_command)
    try:
      subprocess.check_call(geogrid_command, cwd=self.wps_workdir,
                            stdout=utils.devnull(), stderr=utils.devnull())
    except CalledProcessError:
      logger.error('Geogrid failed %s:' %geogrid_command)
      raise  # re-raise exception


  def _run_ungrib(self):
    '''
    run ungrib.exe (locally or using slurm script defined in config.json)
    '''
    if len(self.config['options_slurm']['slurm_ungrib.exe']):
      ungrib_slurm = self.config['slurm']['slurm_ungrib.exe']
      utils.check_file_exists(ungrib_slurm)
      ungrib_command = 'sbatch ' + ungrib_slurm
    else:
      ungrib_command = os.path.join(self.config['filesystem']['wps_dir'],
                              'ungrib', 'ungrib.exe')
      utils.check_file_exists(ungrib_command)
    try:
      subprocess.check_call(ungrib_command, cwd=self.wps_workdir,
                            stdout=utils.devnull(), stderr=utils.devnull())
    except CalledProcessError:
      logger.error('Ungrib failed %s:' %ungrib_command)
      raise  # re-raise exception


  def _run_metgrid(self):
    '''
    run metgrid.exe (locally or using slurm script defined in config.json)
    '''
    if len(self.config['options_slurm']['slurm_metgrid.exe']):
      metgrid_slurm = self.config['slurm']['slurm_metgrid.exe']
      utils.check_file_exists(metgrid_slurm)
      metgrid_command = 'sbatch ' + metgrid_slurm
    else:
      metgrid_command = os.path.join(self.config['filesystem']['wps_dir'],
                              'metgrid', 'metgrid.exe')
      utils.check_file_exists(metgrid_command)
    try:
      subprocess.check_call(metgrid_command, cwd=self.wps_workdir,
                            stdout=utils.devnull(), stderr=utils.devnull())
    except CalledProcessError:
      logger.error('Metgrid failed %s:' %metgrid_command)
      raise  # re-raise exception


if __name__ == "__main__":
  logger = utils.start_logging('test.log')
  boundary_dir = '/home/WUR/haren009/sources/upp_archive/'
  datestart= datetime(2014,07,27,00)
  dateend = datetime(2014,07,27,06)
  runwps = wps(boundary_dir, datestart, dateend)

"""Celery asynchronous tasks for the daq module."""

from celery import shared_task, group
from celery.exceptions import SoftTimeLimitExceeded
from .models import ECCServer, DataRouter
from .workertasks import WorkerInterface

import logging
logger = logging.getLogger(__name__)


@shared_task(soft_time_limit=5, time_limit=10)
def eccserver_refresh_state_task(eccserver_pk):
    """Fetch the state of the given ECC server.

    This will contact the ECC server identified by the given primary key, fetch its state, and
    update the state in the database.

    Parameters
    ----------
    eccserver_pk : int
        The integer primary key of the ECCServer object in the database.

    """
    try:
        ecc_server = ECCServer.objects.get(pk=eccserver_pk)
    except ECCServer.DoesNotExist:
        logger.error('No ECC server exists with pk %d', eccserver_pk)
        return

    try:
        ecc_server.refresh_state()
    except SoftTimeLimitExceeded:
        logger.error('Time limit exceeded while refreshing state of %s', ecc_server.name)
    except Exception:
        logger.exception('Failed to refresh state of ECC server %s', ecc_server.name)


@shared_task(soft_time_limit=8, time_limit=10)
def eccserver_refresh_all_task():
    """Fetch the state of all ECC servers.

    This calls :func:`eccserver_refresh_state_task` for each ECC server in the database.

    """
    try:
        pk_list = [ecc.pk for ecc in ECCServer.objects.all()]
        gp = group([eccserver_refresh_state_task.s(i) for i in pk_list])
        gp()
    except SoftTimeLimitExceeded:
        logger.error('Time limit exceeded while refreshing state of all ECC servers')
    except Exception:
        logger.exception('Failed to refresh state of all ECC servers')


@shared_task(soft_time_limit=45, time_limit=60)
def eccserver_change_state_task(eccserver_pk, target_state):
    """Change the state of an ECC server (make it perform a transition).

    This will contact the ECC server identified by the given primary key and tell it to transition to the given
    target state. This is done by calling :meth:`~attpcdaq.daq.models.ECCServer.change_state` on the
    :class:`~attpcdaq.daq.models.ECCServer` object.

    Parameters
    ----------
    eccserver_pk : int
        The ECC server's integer primary key.
    target_state : int
        The target state. Use one of the constants from the :class:`~attpcdaq.daq.models.ECCServer` class.
    """
    try:
        ecc_server = ECCServer.objects.get(pk=eccserver_pk)
    except ECCServer.DoesNotExist:
        logger.error('No ECC server exists with pk %d', eccserver_pk)
        return

    try:
        ecc_server.change_state(target_state)
    except SoftTimeLimitExceeded:
        logger.error('Time limit exceeded while changing state of %s', ecc_server.name)
    except Exception:
        logger.exception('Failed to change state of %s', ecc_server.name)


@shared_task(soft_time_limit=10, time_limit=40)
def check_ecc_server_online_task(eccserver_pk):
    """Checks if the ECC server is online.

    This is done by checking if the process is running via SSH. Specifically, the method
    :meth:`~attpcdaq.daq.workertasks.WorkerInterface.check_ecc_server_status` of the
    :class:`~attpcdaq.daq.workertasks.WorkerInterface` object is used.

    Parameters
    ----------
    eccserver_pk : int
        The primary key of the ECC server in the database.

    """
    try:
        ecc_server = ECCServer.objects.get(pk=eccserver_pk)
    except ECCServer.DoesNotExist:
        logger.error('No ECC server exists with pk %d', eccserver_pk)
        return

    try:
        with WorkerInterface(ecc_server.ip_address) as wint:
            ecc_alive = wint.check_ecc_server_status()

        ecc_server.is_online = ecc_alive
        ecc_server.save()
    except SoftTimeLimitExceeded:
        logger.error('Time limit exceeded while checking whether %s is online', ecc_server.name)
    except Exception:
        logger.exception('Failed to check whether %s is online', ecc_server.name)


@shared_task(soft_time_limit=60, time_limit=80)
def check_ecc_server_online_all_task():
    """Check and update the state of all known ECC servers.

    This calls :func:`check_ecc_server_online_task` for each ECC server.

    """
    try:
        pks = [e.pk for e in ECCServer.objects.all()]
        gp = group([check_ecc_server_online_task.s(i) for i in pks])
        gp()
    except SoftTimeLimitExceeded:
        logger.error('Time limit exceeded while refreshing state of all ECC servers')
    except Exception:
        logger.exception('Failed to refresh state of all ECC servers')


@shared_task(soft_time_limit=10, time_limit=40)
def check_data_router_status_task(datarouter_pk):
    """Checks whether the data router is online and if the staging directory is clean.

    This is done by checking if the process is running via SSH. Specifically, the method
    :meth:`~attpcdaq.daq.workertasks.WorkerInterface.check_data_router_status` of the
    :class:`~attpcdaq.daq.workertasks.WorkerInterface` object is used. Then, the staging directory
    is checked for GRAW files using :meth:`~attpcdaq.daq.workertasks.WorkerInterface.working_dir_is_clean`
    from the same class.

    Parameters
    ----------
    eccserver_pk : int
        The primary key of the ECC server in the database.

    """
    try:
        data_router = DataRouter.objects.get(pk=datarouter_pk)
    except DataRouter.DoesNotExist:
        logger.error('No data router exists with pk %d', datarouter_pk)
        return

    try:
        with WorkerInterface(data_router.ip_address) as wint:
            data_router_alive = wint.check_data_router_status()
            data_router.is_online = data_router_alive

            if data_router_alive:
                # If the router isn't running, this next step will fail anyway
                staging_dir_clean = wint.working_dir_is_clean()
                data_router.staging_directory_is_clean = staging_dir_clean

        data_router.save()
    except SoftTimeLimitExceeded:
        logger.error('Time limit exceeded while checking whether %s is online', data_router.name)
    except Exception:
        logger.exception('Failed to check whether %s is online', data_router.name)


@shared_task(soft_time_limit=60, time_limit=80)
def check_data_router_status_all_task():
    """Check and update the state of all known data routers.

    This calls :func:`check_data_router_status_task` for each data router.

    """
    try:
        pks = [dr.pk for dr in DataRouter.objects.all()]
        gp = group([check_data_router_status_task.s(i) for i in pks])
        gp()
    except SoftTimeLimitExceeded:
        logger.error('Time limit exceeded while refreshing state of all data routers')
    except Exception:
        logger.exception('Failed to refresh state of all data routers')


@shared_task(soft_time_limit=30, time_limit=40)
def organize_files_task(datarouter_pk, experiment_name, run_number):
    """Connects to the DAQ worker nodes to organize files at the end of a run.

    This is done via SSH using the method
    :meth:`~attpcdaq.daq.workertasks.WorkerInterface.organize_files` of the
    :class:`~attpcdaq.daq.workertasks.WorkerInterface` object.

    Parameters
    ----------
    datarouter_pk : int
        Integer primary key of the data source
    experiment_name : str
        The name of the current experiment
    run_number : int
        The most recent run number

    """
    try:
        router = DataRouter.objects.get(pk=datarouter_pk)
    except DataRouter.DoesNotExist:
        logger.error('No data router exists with pk %d', datarouter_pk)
        return

    try:
        with WorkerInterface(router.ip_address) as wint:
            wint.organize_files(experiment_name, run_number)

        router.staging_directory_is_clean = True
        router.save()

    except SoftTimeLimitExceeded:
        logger.error('Time limit exceeded while organizing files at for data source %s', router.name)
    except Exception:
        logger.exception('Organize files task failed')


@shared_task(soft_time_limit=30, time_limit=40)
def organize_files_all_task(experiment_name, run_number):
    """Organize files on all remote nodes.

    This calls :func:`organize_files_task` for all data routers.

    Parameters
    ----------
    experiment_name : str
        The name of the current experiment
    run_number : int
        The most recent run number

    """
    try:
        pk_list = [router.pk for router in DataRouter.objects.all()]
        gp = group([organize_files_task.s(i, experiment_name, run_number) for i in pk_list])
        gp()
    except SoftTimeLimitExceeded:
        logger.error('Time limit exceeded while rearranging remote files on all nodes')
    except Exception:
        logger.exception('Failed to reorganize files on all nodes')


@shared_task(soft_time_limit=30, time_limit=40)
def backup_config_files_task(ecc_pk, experiment_name, run_number):
    try:
        ecc = ECCServer.objects.get(pk=ecc_pk)
    except ECCServer.DoesNotExist:
        logger.error('No ECC server exists with pk %d', ecc_pk)
        return

    try:
        with WorkerInterface(ecc.ip_address) as wint:
            wint.backup_config_files(experiment_name, run_number, ecc.config_file_paths(), ecc.config_backup_root)

    except SoftTimeLimitExceeded:
        logger.error('Time limit exceeded while backing up configs for ECC server %s', ecc.name)
    except Exception:
        logger.exception('Config backup failed')


@shared_task(soft_time_limit=30, time_limit=40)
def backup_config_files_all_task(experiment_name, run_number):
    try:
        pk_list = [ecc.pk for ecc in ECCServer.objects.all()]
        gp = group([backup_config_files_task.s(pk, experiment_name, run_number) for pk in pk_list])
        gp()
    except SoftTimeLimitExceeded:
        logger.error('Time limit exceeded while backing up config files on all nodes')
    except Exception:
        logger.exception('Failed to back up config files on all nodes')

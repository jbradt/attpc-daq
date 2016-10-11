"""Tasks to be performed on the DAQ workers, where the data router and ECC server run.

This module uses the Paramiko SSH library to connect to the nodes running the data router to,
for example, organize files at the end of a run.

"""

from paramiko.client import SSHClient
from paramiko.config import SSHConfig
from paramiko import AutoAddPolicy
import os
import re
import shlex


class WorkerInterface(object):
    """An interface to perform tasks on the DAQ worker nodes.

    This is used perform tasks on the computers running the data router and the ECC server. This includes things
    like cleaning up the data files at the end of each run.

    The connection is made using SSH, and the SSH config file at ``config_path`` is honored in making the connection.
    Additionally, the server *must* accept connections authenticated using a public key, and this public key must
    be available in your ``.ssh`` directory.

    Parameters
    ----------
    hostname : str
        The hostname to connect to.
    port : int, optional
        The port that the SSH server is listening on. The default is 22.
    username : str, optional
        The username to use. If it isn't provided, a username will be read from the SSH config file. If no username
        is listed there, the name of the user running the code will be used.
    config_path : str, optional
        The path to the SSH config file. The default is ``~/.ssh/config``.

    """
    def __init__(self, hostname, port=22, username=None, config_path=None):
        self.hostname = hostname
        self.client = SSHClient()

        self.client.load_system_host_keys()
        self.client.set_missing_host_key_policy(AutoAddPolicy())

        if config_path is None:
            config_path = os.path.join(os.path.expanduser('~'), '.ssh', 'config')
        self.config = SSHConfig()
        with open(config_path) as config_file:
            self.config.parse(config_file)

        if hostname in self.config.get_hostnames():
            host_cfg = self.config.lookup(hostname)
            full_hostname = host_cfg.get('hostname', hostname)
            if username is None:
                username = host_cfg.get('user', None)  # If none, it will try the user running the server.
        else:
            full_hostname = hostname

        self.client.connect(full_hostname, port, username=username)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()

    def find_data_router(self):
        """Find the working directory of the data router process.

        The directory is found using ``lsof``, which must be available on the remote system.

        Returns
        -------
        str
            The directory where the data router is running, and therefore writing data.

        Raises
        ------
        RuntimeError
            If ``lsof`` finds something strange instead of a process called ``dataRouter``.

        """
        stdin, stdout, stderr = self.client.exec_command('lsof -a -d cwd -c dataRouter -Fcn')
        for line in stdout:
            if line[0] == 'c' and not re.match('cdataRouter', line):
                raise RuntimeError("lsof found {} instead of dataRouter".format(line[1:].strip()))
            elif line[0] == 'n':
                return line[1:].strip()
        else:
            raise RuntimeError("lsof didn't find dataRouter")

    def get_graw_list(self):
        """Get a list of GRAW files in the data router's working directory.

        Returns
        -------
        list[str]
            A list of the file names.

        """
        pwd = self.find_data_router()

        _, stdout, _ = self.client.exec_command('ls -1 {}'.format(os.path.join(pwd, '*.graw')))

        graws = []
        for line in stdout:
            line = line.strip()
            if re.search(r'\.graw$', line):
                graws.append(line)

        return graws

    def working_dir_is_clean(self):
        """Check if there are GRAW files in the data router's working directory.

        Returns
        -------
        bool
            True if there are files in the working directory, False otherwise.
        """
        return len(self.get_graw_list()) == 0

    def check_process_status(self):
        """Checks if the data router and ECC server are running.

        Returns
        -------
        ecc_server_running, data_router_running : bool
            Each is True if the process is running on the remote node, or False otherwise.

        """

        _, stdout, _ = self.client.exec_command('ps -e')

        ecc_server_running = False
        data_router_running = False
        for line in stdout:
            if re.search(r'getEccSoapServer', line):
                ecc_server_running = True
            elif re.search(r'dataRouter', line):
                data_router_running = True

        return ecc_server_running, data_router_running

    def organize_files(self, experiment_name, run_number):
        """Organize the GRAW files at the end of a run.

        This will get a list of the files written in the working directory of the data router and move them to
        the directory ``./experiment_name/run_name``, which will be created if necessary. For example, if
        the ``experiment_name`` is "test" and the ``run_number`` is 4, the files will be placed in ``./test/run_0004``.

        Parameters
        ----------
        experiment_name : str
            A name for the experiment directory.
        run_number : int
            The current run number.

        """
        pwd = self.find_data_router()
        run_name = 'run_{:04d}'.format(run_number)  # run_0001, run_0002, etc.
        run_dir = os.path.join(pwd, experiment_name, run_name)
        run_dir_esc = shlex.quote(run_dir)

        graws = [shlex.quote(s) for s in self.get_graw_list()]

        self.client.exec_command('mkdir -p {}'.format(run_dir_esc))

        self.client.exec_command('mv {} {}'.format(' '.join(graws), run_dir_esc))

    def tail_file(self, path, num_lines=50):
        """Retrieve the tail of a text file on the remote host.

        Note that this assumes the file is ASCII-encoded plain text.

        Parameters
        ----------
        path : str
            Path to the file.
        num_lines : int
            The number of lines to include.

        Returns
        -------
        str
            The tail of the file's contents.
        """
        _, stdout, _ = self.client.exec_command('tail -n {:d} {:s}'.format(num_lines, path))
        return stdout.read().decode('ascii')

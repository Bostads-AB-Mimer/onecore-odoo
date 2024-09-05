import subprocess
import sys
import logging

class Setup:

    @staticmethod
    def install_required_packages():
        try:
            get_packages = subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'])
            installed_packages = [r.decode().split('==')[0] for r in get_packages.split()]

            required_packages = ['python-dotenv']
            for package in required_packages:
                if package in installed_packages:
                    logging.info('Package %s already installed', package)
                else:
                    logging.info('Installing package %s', package)
                    result = subprocess.run([sys.executable, '-m', 'pip', 'install', package], check=True)
                    if result.returncode == 0:
                        logging.info('Successfully installed package %s', package)
                    else:
                        logging.error('Failed to install package %s', package)
        except subprocess.CalledProcessError as e:
            logging.error('Failed to get installed packages: %s', e)
        except Exception as e:
            logging.error('An error occurred: %s', e)
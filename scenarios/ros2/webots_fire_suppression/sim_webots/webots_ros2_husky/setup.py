from setuptools import find_packages, setup
from glob import glob
import os

package_name = 'webots_ros2_husky'
data_files = []
data_files.append(('share/ament_index/resource_index/packages', ['resource/' + package_name]))
data_files.append(('share/' + package_name + '/protos', ['protos/Fire_UGV.proto']))
data_files.append(('share/' + package_name + '/protos', ['protos/Fire.proto']))
data_files.append(('share/' + package_name + '/worlds', ['worlds/fire_suppression.wbt']))
data_files.append(('share/' + package_name + '/resource', ['resource/ros2control.yaml']))
data_files.append(('share/' + package_name + '/resource', ['resource/husky.urdf']))
data_files.append(('share/' + package_name + '/launch', ['launch/robot_launch.py']))
data_files.append(('share/' + package_name, ['package.xml']))
data_files.append(('share/' + package_name + '/worlds/icons', ['worlds/icons/base.png']))
data_files.append(('share/' + package_name + '/worlds/icons', ['worlds/icons/rescue_white.png']))
data_files.append(('share/' + package_name + '/worlds/icons', ['worlds/icons/rescue_red.png']))
data_files.append(('share/' + package_name + '/worlds/icons', ['worlds/icons/target_unchecked.png']))
data_files.append(('share/' + package_name + '/worlds/icons', ['worlds/icons/target_checked.png']))
data_files.append(('share/' + package_name + '/worlds/icons', ['worlds/icons/mavic_fast_helix.png']))
data_files.append(('share/' + package_name + '/controllers/world_supervisor', ['controllers/world_supervisor/world_supervisor.py']))
data_files.append(('share/' + package_name + '/controllers/robot_supervisor', ['controllers/robot_supervisor/robot_supervisor.py']))

# Add all files from husky_description directory
husky_desc_dir = 'resource/husky_description'
if os.path.exists(husky_desc_dir):
    for root, dirs, files in os.walk(husky_desc_dir):
        for file in files:
            src_file = os.path.join(root, file)
            dest_dir = os.path.join('share', package_name, root)
            data_files.append((dest_dir, [src_file]))



setup(
    name=package_name,
    version='0.0.0',
    packages=[package_name],
    data_files=data_files,
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='your_name',
    maintainer_email='your_email_address',
    description='TODO: Package description',
    license='Apache-2.0',
    # tests_require=['pytest'],
    entry_points={
        'console_scripts': [
        ],
    },
)
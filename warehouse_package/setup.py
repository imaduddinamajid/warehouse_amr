from setuptools import find_packages, setup

package_name = 'warehouse_package'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Developer',
    maintainer_email='imaduddinamajid@gmail.com',
    description='Warehouse Navigation Coordinator',
    license='Apache-2.0',
    extras_require={
        'test': ['pytest'],
    },
    entry_points={
        'console_scripts': [
            'warehouse_brain = warehouse_package.warehouse_brain:main',
        ],
    },
)

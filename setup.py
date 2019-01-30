import os
import time

from setuptools import setup, find_packages
from io import open


# allow setup.py to be run from any path
os.chdir(os.path.normpath(os.path.join(os.path.abspath(__file__), os.pardir)))

with open('README.md', encoding='utf-8') as f:
    long_description = f.read()

if os.path.exists("./VERSION"):
    with open("./VERSION", "r") as f:
        AVI_PIP_VERSION = f.readline()
else:
    ct = time.gmtime()
    date = "%d%02d%02d" % (ct.tm_year, ct.tm_mon, ct.tm_mday)
    AVI_PIP_VERSION = '18.2b' + date
    with open("./VERSION", "w+", encoding='utf-8') as f:
        f.write(u"{}".format(AVI_PIP_VERSION))

setup(
    name='avi-lbaasv2',
    version=AVI_PIP_VERSION,
    description='Avi OpenStack LBaaS v2.0 Driver',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='http://www.avinetworks.com',
    author='Avi Networks',
    author_email='support@avinetworks.com',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: OpenStack',
        'Intended Audience :: Information Technology',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
    ],
    packages=find_packages(exclude=['docs', 'tests']),
    install_requires=[],
    license='LICENSE',
    keywords='avi lbaasv2 openstack loadbalancer'
)

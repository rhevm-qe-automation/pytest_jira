from setuptools import setup

setup(
    name="pytest-marker-jira",
    version="0.01",
    description='py.test JIRA integration plugin, using markers',
    long_description=open('README.md').read(),
    license='GPL',
    author='James Laska',
    author_email='james.laska@gmail.com' ,
    url='http://github.com/eanxgeek/pytest_marker_jira',
    platforms=['linux', 'osx', 'win32'],
    py_modules=['pytest_marker_jira'],
    entry_points = {'pytest11': ['pytest_marker_jira = pytest_marker_jira'],},
    zip_safe=False,
    install_requires = ['jira-python>=0.13','pytest>=2.2.4'],
    classifiers=[
    'Development Status :: 3 - Alpha',
    'Intended Audience :: Developers',
    'License :: OSI Approved :: GNU General Public License (GPL)',
    'Operating System :: POSIX',
    'Operating System :: Microsoft :: Windows',
    'Operating System :: MacOS :: MacOS X',
    'Topic :: Software Development :: Testing',
    'Topic :: Software Development :: Quality Assurance',
    'Topic :: Utilities',
    'Programming Language :: Python',
    ],
)

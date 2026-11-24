"""Start-up shared by every entry point: pick the work dir, re-run under the kit's venv if needed, find the engine."""
import os, sys

KIT = os.path.dirname(os.path.abspath(__file__))
HOME = os.environ.get('CLIPKIT_HOME', os.path.join(os.path.expanduser('~'), '.cache', 'clipkit'))


def boot(need_work=True, need=('scipy', 'soundfile', 'cv2')):
    argv = sys.argv
    work = None
    for i, a in enumerate(argv):
        if a == '--work' and i + 1 < len(argv): work = argv[i + 1]
        elif a.startswith('--work='): work = a.split('=', 1)[1]
    if work:
        os.environ['CLIPKIT_WORK'] = os.path.abspath(work)
    os.environ.setdefault('CLIPKIT_MODELS', os.path.join(HOME, 'models'))
    helping = any(a in ('-h', '--help') for a in argv)
    if need_work and not helping and not os.environ.get('CLIPKIT_WORK'):
        sys.exit('give the work directory: --work DIR (or set CLIPKIT_WORK)')
    try:
        for m in need: __import__(m)
    except ImportError:
        py = os.environ.get('CLIPKIT_PY') or os.path.join(HOME, 'venv', 'bin', 'python')
        # a venv's python is a symlink to the system one, so compare by a flag, not by path (no endless loop)
        if os.path.exists(py) and not os.environ.get('CLIPKIT_REEXEC'):
            os.environ['CLIPKIT_REEXEC'] = '1'
            os.execv(py, [py] + argv)
        sys.exit(f'missing Python packages ({", ".join(need)}): run scripts/setup.sh first (or set CLIPKIT_PY)')
    sys.path.insert(0, os.path.join(KIT, 'clipkit'))


def add_work_arg(ap):
    ap.add_argument('--work', help='work directory (default $CLIPKIT_WORK). Holds shoot.json, manifest.json, audio/, '
                                   'transcript/, clips/, out/')

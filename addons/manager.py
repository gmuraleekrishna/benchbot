# Python manager for BenchBot Add-ons
import json
import re
import requests
import os
from shutil import rmtree
from subprocess import PIPE, run
import yaml

DEFAULT_INSTALL_LOCATION = '.'
DEFAULT_STATE_PATH = '.state'

ENV_INSTALL_LOCATION = 'INSTALL_LOCATION'
ENV_STATE_PATH = 'STATE_PATH'

FILENAME_DEPENDENCIES = '.dependencies'
FILENAME_REMOTE = '.remote'

HASH_SHORT = 8

SUPPORTED_TYPES = [
    'environments', 'evaluation', 'ground_truths', 'robots', 'tasks'
]

URL_OFFICIAL_ADDONS = 'https://github.com/benchbot-addons'


def _abs_path(path):
    return (path if path.startswith('/') else os.path.abspath(
        os.path.join(os.path.dirname(__file__), path)))


def _addon_path(repo_user, repo_name):
    return os.path.join(_install_location(), repo_user, repo_name)


def _install_location():
    return _abs_path(
        os.environ.get(ENV_INSTALL_LOCATION, DEFAULT_INSTALL_LOCATION))


def _parse_name(name):
    # Support both 'repo_owner/repo_name' &
    # 'https://github.com/repo_owner/repo_name' syntax
    url = name if name.startswith('http') else 'https://github.com/%s' % name
    repo_user, repo_name = re.search('[^/]*/[^/]*$', url).group().split('/')
    return url, repo_user, repo_name, '%s/%s' % (repo_user, repo_name)


def _state_path():
    return _abs_path(os.environ.get(ENV_STATE_PATH, DEFAULT_STATE_PATH))


def _validate_type(type_string):
    if type_string not in SUPPORTED_TYPES:
        raise ValueError(
            "Resource type '%s' is not one of the supported types:\n\t%s" %
            (type_string, SUPPORTED_TYPES))


def dump_state(state):
    # State is a dictionary with:
    # - keys for each installed addon
    # - each key has: 'hash', 'remote' (if remote content installed), & 'deps'
    #   list
    with open(_state_path(), 'w+') as f:
        json.dump(state, f, indent=4)


def find_all(type_string):
    _validate_type(type_string)
    return [
        s for s in
        run('find . -regex \'.*/%s/[^/]*ya?ml\' | xargs readlink -f' %
            type_string,
            shell=True,
            cwd=_install_location(),
            capture_output=True).stdout.decode('utf8').strip().splitlines()
    ]


def get_contents(type_string, name):
    _validate_type(type_string)


def get_field(type_string, field_name):
    _validate_type(type_string)
    return [yaml.safe_load(open(f))[field_name] for f in find_all(type_string)]


def get_state():
    if os.path.exists(_state_path()):
        with open(_state_path(), 'r') as f:
            return json.load(f)
    return {}


def install_addon(name):
    url, repo_user, repo_name, name = _parse_name(name)
    install_path = _addon_path(repo_user, repo_name)

    print("Installing addon '%s' in '%s':" % (name, _install_location()))

    # Make sure the target location exists
    if not os.path.exists(install_path):
        os.makedirs(install_path)
        print("\tCreated install path './%s'." %
              os.path.relpath(install_path, _install_location()))
    else:
        print("\tFound install path './%s'." %
              os.path.relpath(install_path, _install_location()))

    # Either clone the addon or upgrade to latest
    cmd_args = {
        'shell': True,
        'cwd': install_path,
        'capture_output': True,
    }
    if not os.path.exists(os.path.join(install_path, '.git')):
        ret = run('git clone %s .' % url, **cmd_args)
        if ret.returncode == 0:
            print("\tCloned addon from '%s'." % url)
        else:
            raise RuntimeError("Failed to clone '%s' from '%s'.\n"
                               "Are you sure the repository exists?" %
                               (name, url))
        current = run('git rev-parse HEAD',
                      **cmd_args).stdout.decode('utf8').strip()
    else:
        run('git fetch --all', **cmd_args)
        current = run('git rev-parse HEAD',
                      **cmd_args).stdout.decode('utf8').strip()
        latest = run('git rev-parse origin/HEAD',
                     **cmd_args).stdout.decode('utf8').strip()
        if current == latest:
            print("\tNo action - latest already installed.")
        else:
            run('git reset --hard origin/HEAD', **cmd_args)
            print("\tUpgraded from '%s' to '%s'." %
                  (current[:HASH_SHORT], latest[:HASH_SHORT]))

    # Fetch remote data if required
    file_remote = os.path.join(install_path, FILENAME_REMOTE)
    if os.path.exists(file_remote):
        with open(file_remote, 'r') as f:
            remote, target = f.readlines()[0].strip().split(' ')
            print("\tFound remote content to install to '%s': %s" %
                  (target, remote))
            state = get_state()
            if ('remote' not in state[name] or state[name]['remote'] != remote
                    or 'remote_target' not in state[name]
                    or state[name]['remote_target'] != target):
                print("\tRemote content is new. Fetching ...")
                if (run('wget "%s" -O ".tmp.zip"' % remote, **{
                        **cmd_args, 'capture_output': False
                }).returncode != 0):
                    print("\tFetching of remote content FAILED!!!")
                else:
                    print("\tFetched.")
                    target_abs = os.path.join(install_path, target)
                    if os.path.exists(target_abs):
                        print("\tRemoved existing target '%s'." % target)
                        run('rm -r "%s"' % target_abs, **cmd_args)
                    print("\tExtracting to '%s' ..." % target)
                    run('unzip -d "%s" ".tmp.zip"' % target, **cmd_args)
                    print("\tExtracted.")
                    state[name]['remote'] = remote
                    state[name]['remote_target'] = target
                    dump_state(state)
            else:
                print("\tNo action - remote content is already installed.")

    # Install all dependencies
    file_deps = os.path.join(install_path, FILENAME_DEPENDENCIES)
    if os.path.exists(file_deps):
        with open(file_deps, 'r') as f:
            deps = f.read().splitlines()
    else:
        deps = []
    ret = [name]
    for d in deps:
        ret.extend(install_addon(d))

    # Update the saved state
    state = get_state()
    if name not in state:
        state[name] = {}
    state[name]['hash'] = current
    state[name]['deps'] = deps
    dump_state(state)
    return ret


def install_addons(string, remove_extras=False):
    installed_list = []
    for a in string.split(','):
        installed_list.extend(install_addon(a))
    if remove_extras:
        # TODO remove any not in installed_list
        pass
    return installed_list


def print_state():
    state = get_state()
    print("Currently installed add-ons:")
    if not state.keys():
        print("\tNone.")
    else:
        for k, v in state.items():
            print("\t%s (%s%s)" %
                  (k, v['hash'][:HASH_SHORT],
                   ', with remote content' if 'remote' in v else ''))
    print(
        "\nOur GitHub organisation (https://github.com/benchbot-addons) "
        "contains all of our official add-ons.\nThe following are available, "
        "with more details available at the above URL:")
    for o in official_addons():
        print("\t%s" % o)

    print("\nIf you would like to add your community-created add-on to the "
          "official list, please follow the\ninstructions here:\n\t"
          "https://github.com/RoboticVisionOrg/benchbot/wiki/BenchBot-Add-ons")


def official_addons():
    # Get repository list from the GitHub organisation
    offical_org = URL_OFFICIAL_ADDONS.split('/')[-1]
    repo_data = requests.get('https://api.github.com/orgs/%s/repos' %
                             offical_org,
                             headers={
                                 'Accept': 'application/vnd.github.v3+json'
                             }).json()
    return [d['full_name'] for d in repo_data]


def remove_addon(name):
    url, repo_user, repo_name, name = _parse_name(name)
    install_path = _addon_path(repo_user, repo_name)
    install_parent = os.path.dirname(install_path)

    # Confirm the addon exists
    if not os.path.exists(install_path):
        raise RuntimeError(
            "Are you sure addon '%s' is installed? It was not found at:\n\t%s"
            % (name, install_path))

    # Remove the directory (& parent if now empty)
    print("Removing addon '%s' in '%s':" % (name, _install_location()))
    rmtree(install_path)
    print("\tRemoved installed directory './%s'" %
          os.path.relpath(install_path, _install_location()))
    if os.path.exists(install_parent) and not os.listdir(install_parent):
        os.rmdir(install_parent)
        print("\tRemoved empty parent directory './%s'" %
              os.path.relpath(install_parent, _install_location()))

    # Redump installed state
    state = get_state()
    del state[name]
    dump_state(state)


def remove_addons(string=None, remove_dependents=True):
    # Ensure a usable string
    if string is None or string == "":
        string = ",".join(get_state().keys())
    if string == "":
        return
    addons = string.split(',')

    # Add dependents to the list if requested
    state = get_state()
    deps = []
    if remove_dependents:
        for a in addons:
            deps.extend([k for k in state.keys() if a in state[k]['deps']])
    print("Removing the following requested add-ons:")
    for a in addons:
        print("\t%s" % a)
    if deps:
        print("and the following dependent add-ons:")
        for d in deps:
            print("\t%s" % d)
    if input("Are you sure you wish to continue [y/N]? ") not in [
            'y', 'Y', 'yes'
    ]:
        return
    addons.extend(deps)
    print("\n")

    for a in addons:
        remove_addon(a)

# Copyright 2013: Mirantis Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from __future__ import print_function

import argparse
import inspect
import os
import sys
import warnings

import jsonschema
from oslo_config import cfg
from oslo_utils import encodeutils
import prettytable
import six

from rally.common.i18n import _
from rally.common import log as logging
from rally.common import utils
from rally.common import version
from rally import exceptions


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


# Some CLI-specific constants
MARGIN = 3


class MissingArgs(Exception):
    """Supplied arguments are not sufficient for calling a function."""
    def __init__(self, missing):
        self.missing = missing
        msg = _("Missing arguments: %s") % ", ".join(missing)
        super(MissingArgs, self).__init__(msg)


def validate_args(fn, *args, **kwargs):
    """Check that the supplied args are sufficient for calling a function.

    >>> validate_args(lambda a: None)
    Traceback (most recent call last):
        ...
    MissingArgs: Missing argument(s): a
    >>> validate_args(lambda a, b, c, d: None, 0, c=1)
    Traceback (most recent call last):
        ...
    MissingArgs: Missing argument(s): b, d

    :param fn: the function to check
    :param arg: the positional arguments supplied
    :param kwargs: the keyword arguments supplied
    """
    argspec = inspect.getargspec(fn)

    num_defaults = len(argspec.defaults or [])
    required_args = argspec.args[:len(argspec.args) - num_defaults]

    def isbound(method):
        return getattr(method, "__self__", None) is not None

    if isbound(fn):
        required_args.pop(0)

    missing = [arg for arg in required_args if arg not in kwargs]
    missing = missing[len(args):]
    if missing:
        raise MissingArgs(missing)


def print_list(objs, fields, formatters=None, sortby_index=0,
               mixed_case_fields=None, field_labels=None):
    """Print a list or objects as a table, one row per object.

    :param objs: iterable of :class:`Resource`
    :param fields: attributes that correspond to columns, in order
    :param formatters: `dict` of callables for field formatting
    :param sortby_index: index of the field for sorting table rows
    :param mixed_case_fields: fields corresponding to object attributes that
        have mixed case names (e.g., 'serverId')
    :param field_labels: Labels to use in the heading of the table, default to
        fields.
    """
    formatters = formatters or {}
    mixed_case_fields = mixed_case_fields or []
    field_labels = field_labels or fields
    if len(field_labels) != len(fields):
        raise ValueError(_("Field labels list %(labels)s has different number "
                           "of elements than fields list %(fields)s"),
                         {"labels": field_labels, "fields": fields})

    if sortby_index is None:
        kwargs = {}
    else:
        kwargs = {"sortby": field_labels[sortby_index]}
    pt = prettytable.PrettyTable(field_labels)
    pt.align = "l"

    for o in objs:
        row = []
        for field in fields:
            if field in formatters:
                row.append(formatters[field](o))
            else:
                if field in mixed_case_fields:
                    field_name = field.replace(" ", "_")
                else:
                    field_name = field.lower().replace(" ", "_")
                data = getattr(o, field_name, "")
                row.append(data)
        pt.add_row(row)

    if six.PY3:
        print(encodeutils.safe_encode(pt.get_string(**kwargs)).decode())
    else:
        print(encodeutils.safe_encode(pt.get_string(**kwargs)))


def make_header(text, size=80, symbol="-"):
    """Unified way to make header message to CLI.

    :param text: what text to write
    :param size: Length of header decorative line
    :param symbol: What symbol to use to create header
    """
    header = symbol * size + "\n"
    header += " %s\n" % text
    header += symbol * size + "\n"
    return header


def suppress_warnings(f):
    f._suppress_warnings = True
    return f


class CategoryParser(argparse.ArgumentParser):

    """Customized arguments parser

    We need this one to override hardcoded behavior.
    So, we want to print item's help instead of 'error: too few arguments'.
    Also, we want not to print positional arguments in help messge.
    """

    def format_help(self):
        formatter = self._get_formatter()

        # usage
        formatter.add_usage(self.usage, self._actions,
                            self._mutually_exclusive_groups)

        # description
        formatter.add_text(self.description)

        # positionals, optionals and user-defined groups
        # INFO(oanufriev) _action_groups[0] contains positional arguments.
        for action_group in self._action_groups[1:]:
            formatter.start_section(action_group.title)
            formatter.add_text(action_group.description)
            formatter.add_arguments(action_group._group_actions)
            formatter.end_section()

        # epilog
        formatter.add_text(self.epilog)

        # determine help from format above
        return formatter.format_help()

    def error(self, message):
        self.print_help(sys.stderr)
        sys.exit(2)


def pretty_float_formatter(field, ndigits=None):
    """Create a formatter function for the given float field.

    :param field: a float object attribute name to be formatted.
    :param ndigits: The number of digits after decimal point after round.
    If None, then no rounding will be done.
    :returns: the formatter function
    """

    def _formatter(obj):
        value = getattr(obj, field)
        if value is not None:
            if ndigits is not None:
                return round(value, ndigits)
            else:
                return value
        else:
            return "n/a"
    return _formatter


def args(*args, **kwargs):
    def _decorator(func):
        func.__dict__.setdefault("args", []).insert(0, (args, kwargs))
        return func
    return _decorator


def alias(command_name):
    """Allow cli to use alias command name instead of function name.

    :param command_name: desired command name
    """
    def decorator(func):
        func.alias = command_name
        return func
    return decorator


def deprecated_args(*args, **kwargs):
    def _decorator(func):
        func.__dict__.setdefault("args", []).insert(0, (args, kwargs))
        func.__dict__.setdefault("deprecated_args", [])
        func.deprecated_args.append(args[0])
        if "help" in kwargs.keys():
            warn_message = "DEPRECATED!"
            kwargs["help"] = " ".join([warn_message, kwargs["help"]])
        return func
    return _decorator


def _methods_of(cls):
    """Get all callable methods of a class that don't start with underscore.

    :returns: a list of tuples of the form (method_name, method)
    """
    # The idea of unbound methods exists in Python 2 and was removed in
    # Python 3, so "inspect.ismethod" is used here for Python 2 and
    # "inspect.isfunction" for Python 3.
    all_methods = inspect.getmembers(
        cls, predicate=lambda x: inspect.ismethod(x) or inspect.isfunction(x))
    methods = [m for m in all_methods if not m[0].startswith("_")]
    return methods


def _compose_category_description(category):

    descr_pairs = _methods_of(category)

    description = ""
    doc = category.__doc__
    if doc:
        description = doc.strip()
    if descr_pairs:
        description += "\n\nCommands:\n"
        sublen = lambda item: len(item[0])
        first_column_len = max(map(sublen, descr_pairs)) + MARGIN
        for item in descr_pairs:
            name = getattr(item[1], "alias", item[0])
            if item[1].__doc__:
                doc = utils.parse_docstring(
                    item[1].__doc__)["short_description"]
            else:
                doc = ""
            name += " " * (first_column_len - len(name))
            description += "   %s%s\n" % (name, doc)

    return description


def _compose_action_description(action_fn):
    description = ""
    if action_fn.__doc__:
        parsed_doc = utils.parse_docstring(action_fn.__doc__)
        short = parsed_doc.get("short_description")
        long = parsed_doc.get("long_description")

        description = "%s\n\n%s" % (short, long) if long else short

    return description


def _add_command_parsers(categories, subparsers):

    # INFO(oanufriev) This monkey patching makes our custom parser class to be
    # used instead of native.  This affects all subparsers down from
    # 'subparsers' parameter of this function (categories and actions).
    subparsers._parser_class = CategoryParser

    parser = subparsers.add_parser("version")

    parser = subparsers.add_parser("bash-completion")
    parser.add_argument("query_category", nargs="?")

    for category in categories:
        command_object = categories[category]()
        descr = _compose_category_description(categories[category])
        parser = subparsers.add_parser(
            category, description=descr,
            formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.set_defaults(command_object=command_object)

        category_subparsers = parser.add_subparsers(dest="action")

        for method_name, method in _methods_of(command_object):
            descr = _compose_action_description(method)
            parser = category_subparsers.add_parser(
                getattr(method, "alias", method_name),
                formatter_class=argparse.RawDescriptionHelpFormatter,
                description=descr, help=descr)

            action_kwargs = []
            for args, kwargs in getattr(method, "args", []):
                # FIXME(markmc): hack to assume dest is the arg name without
                # the leading hyphens if no dest is supplied
                kwargs.setdefault("dest", args[0][2:])
                action_kwargs.append(kwargs["dest"])
                kwargs["dest"] = "action_kwarg_" + kwargs["dest"]
                parser.add_argument(*args, **kwargs)

            parser.set_defaults(action_fn=method)
            parser.set_defaults(action_kwargs=action_kwargs)
            parser.add_argument("action_args", nargs="*")


def validate_deprecated_args(argv, fn):
    if (len(argv) > 3
       and (argv[2] == fn.__name__)
       and getattr(fn, "deprecated_args", None)):
        for item in fn.deprecated_args:
            if item in argv[3:]:
                LOG.warning("Deprecated argument %s for %s." % (item,
                                                                fn.__name__))


def run(argv, categories):
    parser = lambda subparsers: _add_command_parsers(categories, subparsers)
    category_opt = cfg.SubCommandOpt("category",
                                     title="Command categories",
                                     help="Available categories",
                                     handler=parser)

    CONF.register_cli_opt(category_opt)

    try:
        CONF(argv[1:], project="rally", version=version.version_string())
        logging.setup("rally")
        if not CONF.get("log_config_append"):
            # The below two lines are to disable noise from request module. The
            # standard way should be we make such lots of settings on the root
            # rally. However current oslo codes doesn't support such interface.
            # So I choose to use a 'hacking' way to avoid INFO logs from
            # request module where user didn't give specific log configuration.
            # And we could remove this hacking after oslo.log has such
            # interface.
            LOG.debug("INFO logs from urllib3 and requests module are hide.")
            requests_log = logging.getLogger("requests").logger
            requests_log.setLevel(logging.WARNING)
            urllib3_log = logging.getLogger("urllib3").logger
            urllib3_log.setLevel(logging.WARNING)

    except cfg.ConfigFilesNotFoundError:
        cfgfile = CONF.config_file[-1] if CONF.config_file else None
        if cfgfile and not os.access(cfgfile, os.R_OK):
            st = os.stat(cfgfile)
            print(_("Could not read %s. Re-running with sudo") % cfgfile)
            try:
                os.execvp("sudo", ["sudo", "-u", "#%s" % st.st_uid] + sys.argv)
            except Exception:
                print(_("sudo failed, continuing as if nothing happened"))

        print(_("Please re-run %s as root.") % argv[0])
        return(2)

    if CONF.category.name == "version":
        print(version.version_string())
        return(0)

    if CONF.category.name == "bash-completion":
        print(_generate_bash_completion_script())
        return(0)

    fn = CONF.category.action_fn
    fn_args = [encodeutils.safe_decode(arg)
               for arg in CONF.category.action_args]
    fn_kwargs = {}
    for k in CONF.category.action_kwargs:
        v = getattr(CONF.category, "action_kwarg_" + k)
        if v is None:
            continue
        if isinstance(v, six.string_types):
            v = encodeutils.safe_decode(v)
        fn_kwargs[k] = v

    # call the action with the remaining arguments
    # check arguments
    try:
        validate_args(fn, *fn_args, **fn_kwargs)
    except MissingArgs as e:
        # NOTE(mikal): this isn't the most helpful error message ever. It is
        # long, and tells you a lot of things you probably don't want to know
        # if you just got a single arg wrong.
        print(fn.__doc__)
        CONF.print_help()
        print("Missing arguments:")
        for missing in e.missing:
            for arg in fn.args:
                if arg[1].get("dest", "").endswith(missing):
                    print(" " + arg[0][0])
                    break
        return(1)

    try:
        utils.load_plugins("/opt/rally/plugins/")
        utils.load_plugins(os.path.expanduser("~/.rally/plugins/"))

        validate_deprecated_args(argv, fn)

        if getattr(fn, "_suppress_warnings", False):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ret = fn(*fn_args, **fn_kwargs)
        else:
            ret = fn(*fn_args, **fn_kwargs)
        return(ret)

    except (IOError, TypeError, ValueError, exceptions.DeploymentNotFound,
            exceptions.TaskNotFound, jsonschema.ValidationError) as e:
        if logging.is_debug():
            LOG.exception(e)
        print(e)
        return 1
    except Exception:
        print(_("Command failed, please check log for more info"))
        raise


def _generate_bash_completion_script():
    from rally.cmd import main
    bash_data = """
#!/bin/bash

_rally()
{
    declare -A SUBCOMMANDS
    declare -A OPTS

%(data)s

    for OPT in ${!OPTS[*]} ; do
        CMD=${OPT%%%%_*}
        CMDSUB=${OPT#*_}
        SUBCOMMANDS[${CMD}]+="${CMDSUB} "
    done

    COMMANDS="${!SUBCOMMANDS[*]}"
    COMPREPLY=()

    local cur="${COMP_WORDS[COMP_CWORD]}"
    local prev="${COMP_WORDS[COMP_CWORD-1]}"

    if [[ $cur =~ (\.|\~|\/).* ]] ; then
        _filedir
    elif [ $COMP_CWORD == "1" ] ; then
        COMPREPLY=($(compgen -W "$COMMANDS" -- ${cur}))
    elif [ $COMP_CWORD == "2" ] ; then
        COMPREPLY=($(compgen -W "${SUBCOMMANDS[${prev}]}" -- ${cur}))
    else
        if [ $prev == "--filename" ] ; then
            _filedir "@(json|ya?ml)"
        elif [ $prev == "--output-file" ] || [ $prev == "--out" ]; then
            _filedir
        else
            COMMAND="${COMP_WORDS[1]}_${COMP_WORDS[2]}"
            COMPREPLY=($(compgen -W "${OPTS[$COMMAND]}" -- ${cur}))
        fi
    fi
    return 0
}
complete -F _rally rally
"""
    completion = []
    for category, cmds in main.categories.items():
        for name, command in _methods_of(cmds):
            command_name = getattr(command, "alias", name)
            args_list = []
            for arg in getattr(command, "args", []):
                if getattr(command, "deprecated_args", []):
                    if arg[0][0] not in command.deprecated_args:
                        args_list.append(arg[0][0])
                else:
                    args_list.append(arg[0][0])
            args = " ".join(args_list)

            completion.append("""    OPTS["{cat}_{cmd}"]="{args}"\n""".format(
                    cat=category, cmd=command_name, args=args))
    return bash_data % {"data": "".join(sorted(completion))}

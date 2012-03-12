import parameter

Parameter = parameter.Parameter


class InstanceCache(type):
    # If we already have an instance of this class, then just return it from the cache
    # The idea is that a Task object X should be able to set up heavy data structures that
    # can be accessed from other Task objects (with dependencies on X). But we need to make
    # sure that X is not instantiated many times.
    __instance_cache = {}

    def __call__(cls, *args, **kwargs):
        def instantiate():
            return super(InstanceCache, cls).__call__(*args, **kwargs)

        h = InstanceCache.__instance_cache

        if h == None:  # disabled
            return instantiate()

        params = cls.get_params()
        param_values = cls.get_param_values(params, args, kwargs)

        k = (cls, tuple(param_values))

        if k not in h:
            h[k] = instantiate()

        return h[k]

    @classmethod
    def clear(self):
        InstanceCache.__instance_cache = {}

    @classmethod
    def disable(self):
        InstanceCache.__instance_cache = None


class MissingParameterException(Exception):
    pass


class Task(object):
    # Something like this...

    __metaclass__ = InstanceCache

    @classmethod
    def get_params(cls):
        # Extract all Argument instances from the class
        # TODO: not really necessary to do multiple times, can we make it run once when the class is created?
        params = []
        for param_name in dir(cls):
            param_obj = getattr(cls, param_name)
            if not isinstance(param_obj, Parameter):
                continue

            params.append((param_name, param_obj))

        # The order the parameters are created matters. See Parameter class
        params.sort(key=lambda t: t[1].counter)
        return params

    @classmethod
    def get_param_values(cls, params, args, kwargs):
        result = {}

        params_dict = dict(params)

        # Fill in the positional arguments
        for i, arg in enumerate(args):
            param_name, param_obj = params[i]
            result[param_name] = arg

        # Then the optional arguments
        for param_name, arg in kwargs.iteritems():
            assert param_name not in result
            assert param_name in params_dict
            result[param_name] = arg

        # Then use the defaults for anything not filled in
        for param_name, param_obj in params:
            if param_name not in result:
                if not param_obj.has_default:
                    raise MissingParameterException("'%s' tasks requires the '%s' parameter to be set" % (cls.__name__, param_name))
                result[param_name] = param_obj.default

        # Sort it by the correct order and make a list
        return [(param_name, result[param_name]) for param_name, param_obj in params]

    def __init__(self, *args, **kwargs):
        params = self.get_params()
        param_values = self.get_param_values(params, args, kwargs)

        # Set all values on class instance
        for key, value in param_values:
            setattr(self, key, value)

        self.__hash = hash(tuple(param_values))
        self.__repr = '%s(%s)' % (self.__class__.__name__, ', '.join(['%s=%s' % (str(k), str(v)) for k, v in param_values]))

    @classmethod
    def from_input(cls, params):
        # Creates an instance from a str->str hash (to be used for cmd line interaction etc)
        kwargs = {}
        for param_name, param in cls.get_params():
            if params[param_name] != None:
                kwargs[param_name] = param.parse(params[param_name])
            else:
                if param.has_default:
                    kwargs[param_name] = param.default
                else:
                    raise MissingParameterException("No value for '%s' submitted and no default value has been assigned." % param_name)

        return cls(**kwargs)

    def __hash__(self):
        return self.__hash

    def __repr__(self):
        return self.__repr

    def complete(self):
        outputs = flatten(self.output())
        if len(outputs) == 0:
            # TODO(erikbern): This will lead to problems for tasks that require
            # a whole bunch of other tasks but do not produce any output. There
            # will be "Unfulfilled deps in run time" exceptions.
            # We should just make sure that all its inputs exist. This should be
            # cached on the object. Alternatively we should make sure that the
            # Task has been run.
            return False

        for output in outputs:
            if not output.exists():
                return False
        else:
            return True

    def output(self):
        return []  # default impl

    def requires(self):
        return []  # default impl

    def input(self):
        return getpaths(self.requires())

    def deps(self):
        # used by scheduler
        return flatten(self.requires())

    def run(self):
        pass  # default impl


class ExternalTask(Task):
    """Subclass for references to external dependencies"""
    run = NotImplemented


def getpaths(struct):
    """ Maps all Tasks in a structured data object to their .output()"""
    if isinstance(struct, Task):
        return struct.output()
    elif isinstance(struct, dict):
        r = {}
        for k, v in struct.iteritems():
            r[k] = getpaths(v)
        return r
    else:
        # Remaining case: assume r is iterable...
        try:
            s = list(struct)
        except TypeError:
            raise Exception('Cannot map %s to Task/dict/list' % str(struct))

        return [getpaths(r) for r in s]


def flatten(struct):
    """Cleates a flat list of all all items in structured output (dicts, lists, items)
    Examples:
    > _flatten({'a': foo, b: bar})
    [foo, bar]
    > _flatten([foo, [bar, troll]])
    [foo, bar, troll]
    > _flatten(foo)
    [foo]
    """
    if struct is None:
        return []
    flat = []
    if isinstance(struct, dict):
        for key, result in struct.iteritems():
            flat += flatten(result)
        return flat

    try:
        # if iterable
        for result in struct:
            flat += flatten(result)
        return flat
    except TypeError:
        pass

    return [struct]

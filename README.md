# Docker PS
This connects to a local instance of the docker daemon. This uses a custom
implementation of docker-py because we wish to exec /bin/bash to obtain a shell
and AttachStdin (which is hardcoded to False in docker-py).

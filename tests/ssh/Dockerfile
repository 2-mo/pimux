FROM pimux-check
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/sh -p x fixture \
    && mkdir -p /run/sshd /opt/pimux-fixture/denied /opt/pimux-fixture/slow
COPY sshd_config /etc/ssh/sshd_config
COPY command.py /opt/pimux-fixture/command.py
COPY start.sh /opt/pimux-fixture/start.sh
RUN printf '#!/bin/sh\necho "permission denied" >&2\nexit 1\n' > /opt/pimux-fixture/denied/tmux \
    && printf '#!/bin/sh\necho $$ > /tmp/slow-query-pid\nsleep 60\n' > /opt/pimux-fixture/slow/nvidia-smi \
    && chmod 755 /opt/pimux-fixture/denied/tmux /opt/pimux-fixture/slow/nvidia-smi
ENTRYPOINT ["/bin/sh", "/opt/pimux-fixture/start.sh"]

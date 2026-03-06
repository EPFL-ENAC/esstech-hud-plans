if [ -n "$SSH_PRIVATE_KEY" ]; then
	mkdir -p /root/.ssh
	chmod 700 /root/.ssh
	echo "$SSH_PRIVATE_KEY" > /root/.ssh/id_ed25519
	chmod 600 /root/.ssh/id_ed25519
	unset SSH_PRIVATE_KEY
fi

curl -sLo /tmp/runai https://rcp-caas-prod.rcp.epfl.ch/cli/linux \
	&& install /tmp/runai /usr/local/bin/runai \
	&& rm /tmp/runai

mkdir -p ~/.kube
if [ ! -f ~/.kube/config ]; then
	curl https://wiki.rcp.epfl.ch/public/files/kube-config.yaml -o ~/.kube/config && chmod 600 ~/.kube/config
fi

# Must run `runai login` manually. Requires web browser interaction

rclone config create jumphost.rcp.epfl.ch sftp host=jumphost.rcp.epfl.ch key_file=/root/.ssh/id_ed25519
uvicorn --host=0.0.0.0 --timeout-keep-alive=0 api.main:app --reload

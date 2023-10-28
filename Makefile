CDN_BUCKET=obsidian_html
PATH="~/Library/Mobile Documents/iCloud~md~obsidian/Documents/personal"

build: requirements
	.venv/bin/python run.py --path ${PATH}
	cp favicon.ico output/

requirements:
	if [ ! -d ".venv" ]; then python -mvenv .venv; fi
	.venv/bin/pip install -r requirements.txt

clean:
	rm -rf output

pull:
	git pull

serve:
	modd

sync:
	s3cmd sync --acl-public output/ s3://llimllib/${CDN_BUCKET}/

# flush the digital ocean CDN cache
flush:
	doctl compute cdn flush \
		$$(doctl compute cdn list --format ID | tail -n1) \
		--files ${CDN_BUCKET}/*

publish: pull build sync flush

.PHONY: build clean pull requirements serve sync flush publish

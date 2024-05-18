CDN_BUCKET = obsidian_html
MDPATH ?= "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/personal"

build: requirements
	.venv/bin/python run.py --path ${MDPATH} --use-git-times --feed link_blog --feed music_blog --feed blog
	cp favicon.ico output/

# only for use in dev, for quick iteration
build-quick:
	.venv/bin/python run.py --path ${MDPATH} --feed link_blog --feed music_blog --feed blog

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
	s3cmd sync --no-mime-magic --guess-mime-type --acl-public --no-preserve \
		output/ s3://llimllib/${CDN_BUCKET}/

# flush the digital ocean CDN cache
flush:
	doctl compute cdn flush \
		$$(doctl compute cdn list --format ID | tail -n1) \
		--files ${CDN_BUCKET}/*

publish: pull build sync flush

.PHONY: build build-quick clean pull requirements serve sync flush publish

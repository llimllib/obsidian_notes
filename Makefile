CDN_BUCKET = obsidian_html
MDPATH ?= "~/code/obsidian-archive/"

build:
	uv run run.py --path ${MDPATH} --use-git-times --feed link_blog --feed music_blog --feed blog
	cp favicon.ico output/

# only for use in dev, for quick iteration
build-quick:
	uv run run.py --path ${MDPATH} --feed link_blog --feed music_blog --feed blog

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

update-dependencies:
	uv sync

.PHONY: build build-quick clean pull serve sync flush publish update-dependencies

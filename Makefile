CDN_BUCKET=obsidian_html

build: requirements
	venv/bin/python run.py
	cp favicon.ico output/

requirements:
	if [ ! -d "venv" ]; then python -mvenv venv; fi
	venv/bin/pip install -r requirements.txt

clean:
	rm -rf output

serve:
	modd

publish:
	s3cmd sync --acl-public output/ s3://llimllib/${CDN_BUCKET}/

# flush the digital ocean CDN cache
flush:
	doctl compute cdn flush \
		$$(doctl compute cdn list --format ID | tail -n1) \
		--files ${CDN_BUCKET}/*

.PHONY: build clean requirements serve publish flush

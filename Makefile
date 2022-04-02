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

.PHONY: build clean requirements serve

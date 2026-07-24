"""The assist runner — an ONLINE model service (see server.py), never imported by ratch.

Unlike the offline Ray Data runners there is no actor module here: assist serves the
annotator's interactive ``MEDIA_ASSIST_URL`` seam as its own image
(.docker/assist-runner.dockerfile) built from this directory's sealed env.
"""

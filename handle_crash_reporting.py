#!/usr/bin/python

# this script is called when the linux kernel terminates a program
# due to a signal.
# By default, a core file is created (if ulimit -c is set to allow it)
# In ubuntu 16.04 for example, a core handler (called apport) is installed.
# 
# 
# upload the corefile to S3 bucket
# send slack message with a link to the corefile, and a stacktrace
#
# dependencies:
# pip install boto boto3 filechunkio slackclient
#
# Setting this script as coredump handler:
# 1. sudo sysctl -w kernel.core_pattern="|/path/to/handle_crash_reporting.py %h.core.%e.%t %s"
# 1.1 to make the change peristent between boots:
#   echo kernel.core_pattern="|/path/to/handle_crash_reporting.py %h.core.%e.%t %s" >> /etc/sysctl.conf
# 2. cp handle_crash_reporting.py /path/to/handle_crash_reporting.py && chmod a+x /path/to/handle_crash_reporting.py
#
# in order to send to AWS S3, some sort of authrization is needed.
# e.g. as IAM role :
# ... "Resource": [ "arn:aws:s3:::myapp-coredumps/*" ]
#
# see man core(5)
# This script is excuted as root by the kernel with cwd = "/".
# so drop this privilage, and cd to the dir where the dying exe is located.
#
# the core data is supplied as stdin to this script
#
# TODO: 
# - remove usage of boto (use only boto3)
# - limit /tmp/log file size
#
# Noam Cohen 2017-03

import sys
import os
import math
import logging

import subprocess
from slackclient import SlackClient

# for aws s3
import boto
import boto3
from filechunkio import FileChunkIO
import gzip


import time

class slack_reporter:
	def post_message(self, sc,text,channel,icon_url,username):
		sc.api_call("chat.postMessage",channel=channel,text=text,username=username,icon_url=icon_url,unfurl_links="true")


	def  report(self, corefile_name, url_to_download, stack):
		token = "your token here"
		channel =  "#my-app_crash_reports" # you should create this channel in Slack before
		username = "coredump reporter"
		icon_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/1/1a/Skull_Icon_%28Noun_Project%29.svg/891px-Skull_Icon_%28Noun_Project%29.svg.png"
		sc = SlackClient(token)
		if url_to_download is None:
			download_ = "\nUploading to S3 failed!"
		else:
			download_ = "\nDownload from " + url_to_download

		self.post_message(sc,"App Crash!\n" + corefile_name + download_ + "\n\nStack: \n"+stack, channel, icon_url, username)

def compress_file(uncompressed_file_name):
	"""write to the compressed , adding '.gz' """
	output = gzip.open(uncompressed_file_name + '.gz', 'wb')
	data = open(uncompressed_file_name,'r').read() # read the whole file into memory. We have a lot of it.
	try:
		output.write(data)
	finally:
		output.close()


def upload_to_s3(bucket_name, file_name):
	"""
	Try to upload the given file to the bucket.
	Use credentials already available in the machine.

	return None if failed, or url to the file if succeeded

	https://github.com/awslabs/aws-python-sample
	"""

	# First, we'll start with Client API for Amazon S3. Let's instantiate a new
	# client object. With no parameters or configuration, boto3 will look for
	# access keys in these places:
	#
	#    1. Environment variables (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)
	#    2. Credentials file (~/.aws/credentials or
	#         C:\Users\USER_NAME\.aws\credentials)
	#    3. AWS IAM role for Amazon EC2 instance
	#       (http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/iam-roles-for-amazon-ec2.html)

	# This method works with small file but not with large (130MB)
	#s3 = boto3.resource('s3')
	#s3.Object(bucket_name, file_name).put(Body=open(file_name, 'rb'))

	# This method works with small file but not with large (130MB)
	s3_client = boto3.client('s3')
	#s3_client.upload_file(file_name, bucket_name, file_name)

	#http://boto.cloudhackers.com/en/latest/s3_tut.html
	# or http://nullege.com/codes/show/src@d@c@dcu.active-memory-0.1.7@dcu@active_memory@upload.py/62/filechunkio.FileChunkIO
	conn = boto.connect_s3()
	if conn is not None:
		logging.info("Connected to S3")
	else:
		logging.warning("Could not connect to S3")
		return None

	bucket = conn.get_bucket(bucket_name)
	print "got the bucket"
	
	source_size = os.stat(file_name).st_size
	if source_size > 1024*1024:
		# zip it
		#print "size before:", source_size
		outfile_name = file_name + ".gz"
		compress_file(file_name)
		file_name = outfile_name
		source_size = os.stat(file_name).st_size
		#print "size after:", source_size

	#  Create a multipart upload request
	mp = bucket.initiate_multipart_upload(os.path.basename(file_name))
	chunk_size = 52428800
	chunk_count = int(math.ceil(source_size / float(chunk_size)))
	
	try:
		for i in range(chunk_count):
			offset = chunk_size * i
			bytes = min(chunk_size, source_size - offset)
			with FileChunkIO(file_name, 'r', offset=offset, bytes=bytes) as fp:
				print "uploading chunk ", i
				mp.upload_part_from_file(fp, part_num=i + 1)
		mp.complete_upload()
		logging.info( "uploading %s completed" % file_name)
		return s3_client.generate_presigned_url('get_object', Params = {'Bucket': bucket_name, 'Key': file_name}, ExpiresIn=3600*24) 
	except Exception as ex:
		logging.error("Exception during uploading file: ", str(ex))
		mp.cancel_upload() 
		return None
	pass


def read_stdin_into_file(filename):
	PY3K = sys.version_info >= (3, 0)

	if PY3K:
		source = sys.stdin.buffer
	else:
		source = sys.stdin
	data = source.read()
	try:
		output = open(file_name,'w')
		output.write(data)
	except Exception as ex:
		logging.error( "can't write to %s. ex= %s" %( file_name, str(ex) ) )
	finally:
		if output is not None:
			output.close()


import os, pwd, grp
# http://stackoverflow.com/questions/2699907/dropping-root-permissions-in-python
def drop_privileges(running_uid, running_gid):
    if os.getuid() != 0:
        # We're not root so, like, whatever dude
        return

    # Remove group privileges
    os.setgroups([])

    # Try setting the new uid/gid
    os.setgid(running_gid)
    os.setuid(running_uid)

    # Ensure a very conservative umask
    old_umask = os.umask(077)



if __name__ == "__main__":
	if len(sys.argv) != 3:
		print "usage: handler <corename> <signal number>"
		exit()
	logging.basicConfig(filename='/tmp/crash_handler.log',level=logging.INFO)
	signal_number = sys.argv[2]
	if signal_number == "6":
		logging.info("called with %s SIGABRT -> doing nothing." % sys.argv[1])
		exit()
	
	os.chdir(os.path.dirname(sys.argv[0])) # so we can write (although not always)
	try:
		logging.debug("running as user (uid) %d"% os.getuid() )
		drop_privileges(os.stat(sys.argv[0]).st_uid, os.stat(sys.argv[0]).st_gid )
		logging.info("after dropping privs: running as user (uid) %d"% os.getuid() )
	except Exception as ex:
		logging.error("drop privileges: %s"% str(ex))
		exit()

	# read the (stdin) core file into a temp file.
	# it would be best if the temp file is in /tmp but I don't see a way
	# to upload to S3 a file "/tmp/x" and have it called there "x"
	file_name = "core." + sys.argv[1]
	read_stdin_into_file(file_name)
	try:
		try:
			res = subprocess.check_output("gdb -q -n -ex bt -batch /opt/local/mediaserver/mediaserver " + file_name, shell=True)
		except Exception as ex:
			print "failed getting the stack trace ", str(ex)
			res = "No stack"
		remote_path = upload_to_s3("media-server-coredumps",file_name )
		reporter = slack_reporter()
		reporter.report(file_name, remote_path, res)
		os.unlink(file_name)
	except Exception as ex:
		logging.error("internal error: %s", str(ex))
		logging.info("the core file is still in %s" % file_name)


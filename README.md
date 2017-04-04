# crash-reporter
A simple script to report core file to a central location.

I wanted to use abrt (https://github.com/abrt/abrt) on ubuntu 16.04 and got into too many trouble porting it.

This script will upload the corefile to S3 bucket
and send slack message with a link to the corefile, and a stacktrace


## Installation

ip install boto boto3 filechunkio slackclient

Setting this script as coredump handler:
1. sudo sysctl -w kernel.core_pattern="|/path/to/handle_crash_reporting.py %h.core.%e.%t %s"
1.1 to make the change peristent between boots:
   echo kernel.core_pattern="|/path/to/handle_crash_reporting.py %h.core.%e.%t %s" >> /etc/sysctl.conf
2. cp handle_crash_reporting.py /path/to/handle_crash_reporting.py && chmod a+x /path/to/handle_crash_reporting.py
3. in Slack, create a channel for the reports
3.1 get a token and put it in the script
4. in order to upload to Amazon S3, you need some sort of API token. 
   Preferably set IAM role. (see aws docs)

## Testing the installation
On the target linux machine: 
- reboot (to make sure the changes persist)
- sleep 1000 &
- kill -SEGV `pidof sleep`

You should get a slack message in a few seconds.
To debug, check /tmp/crash_handler.log


# wdc_app

Active application boot orchestration.

Responsibilities:

- read activation metadata;
- choose confirmed or probationary active slot;
- read and verify WDCB bundle image;
- install manifest-derived capability set;
- derive active runtime limits;
- set safety state to app-running;
- load verified payload through runtime facade;
- clear authorizer and reset limits on teardown.

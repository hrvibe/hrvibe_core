# hrvibe_core
main app

- from setup to reading vacancy - user does on its own, admin just gets notifications when user progress through steps

- admin initiates ai analisys of sourcing criteria 
- one done admin gets sourcing crit visualizaton
- admin push sourcing crit to user
    - if user agrees, admin get notification to proceed
    - if user disagrees, bot asks to provide audio file with comments
        - once user provides audio file, is saved and link goes to admin
        - admin listen, take actions and push sourcing crit again
- once sourcing crit confirmed, admin fetch negotiations for vacany and update DB
- once done admin makes the first touch of all candidates (sends link and changes empl state)
- admin's actions on hold from this moment
- every time applicant record the video => admin is notified 
- once applicant recorded the video admin gets the video and check if it is good enough
- if vidoe is fine, admin starts resume sourcing and resume analysis
- once done admin get recomendation

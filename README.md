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

HH avaialble actions

- отметить отклик прочитанным - POST /negotiations/read
- действия по отклику - PUT negotiations/{collection_name}/{nid}
- Действия по откликам/приглашениям - PUT /negotiations/{id}


Diff between COLLECTIONS and EMPLOYER_STATE:
collections = «папки»/фильтры верхнего уровня (составные правила)
ищем методом: https://api.hh.ru/negotiations/{collection_id}
employer_state = «ярлык стадии» отдельного диалога
ищем внутри коллекций
Коллекция ≈ объединение переговоров с определёнными employer_state и дополнительными условиями (прочитанность, актуальность, закрыт/архив и пр.).

 When pulling negotiations for a vacancy from HH.ru
 there are multiple "collection" types:
"response" - To fetch new applicant applications
"consider"	- For saved but not yet contacted applicants
"phone_interview" - applicants moved to phone screening	When you’ve started initial contact
"interview" - Invited to interview
"offer"	- Job offer sent
"hired"	- applicant hired
"discard" -	Rejected for different reasons
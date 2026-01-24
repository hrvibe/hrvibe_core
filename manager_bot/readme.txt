Backlog:
- if bot stop (manually or restart), task queue will be cleaned => add file storage instead of in-memory
  Cuttent workaround: redeploy at night, after redeploy trigger taks queues manually by admin command

- add in "services.ai_service" ai assistant logic this will help not to send context (vacancy, sourcing criteria, instructions) with each and every resume / there is a draft already / why? save cots for open ai
- идея Сергея - рассылать запрос на видео визитки всем, включая неподходящим - их можно использовать по принципу на безрыбъе и рак рыба или продавать другим пользователям 


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
#!/bin/bash
mongosh nocsentinel --eval "db.changeUserPassword('nocsentinel', '123Admin')"
if [ $? -ne 0 ]; then
    mongosh nocsentinel --eval "db.createUser({user: 'nocsentinel', pwd: '123Admin', roles: ['readWrite']})"
fi
mongosh admin --eval "db.changeUserPassword('nocsentinel', '123Admin')"
if [ $? -ne 0 ]; then
    mongosh admin --eval "db.createUser({user: 'nocsentinel', pwd: '123Admin', roles: [{role: 'readWrite', db: 'nocsentinel'}]})"
fi
systemctl restart nocsentinel
sleep 3
curl -L -s http://localhost:8000/api/system/license

#!/bin/bash
sed -i 's/authorization: enabled/authorization: disabled/' /etc/mongod.conf
systemctl restart mongod
sleep 3
mongosh admin --eval "db.changeUserPassword('nocsentinel', '123Admin')"
if [ $? -ne 0 ]; then
    mongosh admin --eval "db.createUser({user: 'nocsentinel', pwd: '123Admin', roles: [{role: 'userAdminAnyDatabase', db: 'admin'}, {role: 'readWriteAnyDatabase', db: 'admin'}, {role: 'readWrite', db: 'nocsentinel'}]})"
fi
mongosh nocsentinel --eval "db.changeUserPassword('nocsentinel', '123Admin')"
if [ $? -ne 0 ]; then
    mongosh nocsentinel --eval "db.createUser({user: 'nocsentinel', pwd: '123Admin', roles: ['readWrite']})"
fi
sed -i 's/authorization: disabled/authorization: enabled/' /etc/mongod.conf
systemctl restart mongod
systemctl restart nocsentinel
sleep 3
curl -L -s http://localhost:8000/api/system/license

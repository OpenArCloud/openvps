FusionAuth is an authentication backend that can run locally and does not require cloud services.

In the description below, we will assume that the domain name of your OpenVPS is `https://openvps.org` and the following _external_ ports are used:
- 8045 for FusionAuth
- 8046 for MapLocalizer
- 8047 for MapBuilder
- 8048 for MapAligner


## Running locally

1. Download FusionAuth init files

```bash
curl -o docker-compose.yml https://raw.githubusercontent.com/FusionAuth/fusionauth-containers/main/docker/fusionauth/docker-compose.yml

curl -o .env https://raw.githubusercontent.com/FusionAuth/fusionauth-containers/main/docker/fusionauth/.env
```
Change `DATABASE_PASSWORD` to something else in `.env`

Change the port (let's say to `8045`, but the default is `9011`) if you want in the `ports` section of `docker-compose.yml`


2. Start FusionAuth containers in the background by `docker compose up -d`

3. Open `http://localhost:8045/admin` (default `http://localhost:8045/admin`)and register an admin account

## Create a new Tenant
1. Go to Tenants -> New

Pick a suitable name

Set the issuer to your FusionAuth fully qualified public URL: `https://openvps.org:8045`

But if you are using nginx on localhost (see below), write her `https://localhost:9011`


## Create a new application

1. Applications -> "app name" -> Edit
Select the Tenant created above.

This step will create the application's client ID and client secret.
An API key is optional, not needed for now

2. OAuth tab

Assuming that your public URL is `https://openvps.org` and the OpenVPS components are reachable via external ports 8046,8047,8048, the following URLs need to be configured.

add Authorized redirect URLs:
 - https://openvps.org:8047/auth/callback/fusionauth (mapbuilder)
 - https://openvps.org:8048/auth/callback/fusionauth (mapaligner)
 - http://localhost:3001/api/auth/callback/fusionauth (mapaligner)
 - http://localhost:8047/auth/callback/fusionauth (mapbuilder)

add Authorized request URLs:
 - https://openvps.org:8048
 - https://openvps.org:8047
 - https://openvps.org:8046

add Logout URL:
 - https://openvps.org:8047

3. Make sure "Authorization code" is enabled

4. JWT tab -> enable JWT

## Changing "Email" to "Username" in the login form (optional)

(visual difference only)

1. Customizations -> Themes

2. New simple theme

3. Messages -> Default -> Edit

4. Add "loginId=Username" to Custom messages

5. Tenants -> Default -> Edit -> Set theme to new theme


## Adding a `demo` user

1. Users ->  Plus icon

2. Setting an email is not obligatory. Add a username and a password (without sending email)


## Adding user to an application

1. Users -> Select ehe user -> Action -> Manage

2. Add registration -> select our application


## Generate AUTH_SECRET

```bash
openssl rand -base64 33
```

AUTH_SECRET must be the same for all client applications that want to use this authentication service




## NGINX setup for public access

Assuming that `https://openvps.org:8045` is our public domain name and port and assuming that FusionAuth is running on `localhost:18045`, the following nginx configuration block is needed:

```
# 8045 for FusionAuth
server {
    server_name openvps.org;
    listen 8045 ssl;
    listen [::]:8045 ssl;
    root /usr/share/nginx/html;
    location / {
        # note: the trailing slash after the port seems important
        proxy_pass http://127.0.0.1:18045/;
        proxy_redirect off;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host:$server_port;
        proxy_set_header X-Forwarded-Host $host:$server_port;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Port $server_port;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_cache_bypass $http_upgrade;
    }
    ssl_certificate /etc/letsencrypt/live/openvps.org/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/openvps.org/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
}
```


## Forwarding the FusionAuth port from WSL (optional, only Windows)

Open PowerShell as administrator

```powershell
netsh interface portproxy add v4tov4 listenport=9011 listenaddress=0.0.0.0 connectport=9011 connectaddress=172.28.210.6
```

Remove port forwarding

```powershell
netsh interface portproxy delete v4tov4 listenport=9011 listenaddress=0.0.0.0
```

## Running FusionAuth with self-signed SSL certificate on localhost (optional):

1. Insert nginx to docker-compose.yml

```yaml
nginx:
  image: nginx:latest
  ports:
    - 9011:443
  restart: unless-stopped
  networks:
    - db_net
    - search_net
  depends_on:
    fusionauth:
      condition: service_healthy
  volumes:
    - ./nginx/conf/:/etc/nginx/conf.d/
    - ./nginx/certs:/etc/nginx/ssl
```

2.  Comment out "ports" section of `fusionauth` service in docker-compose.yml

```yaml
#    ports:
#      - 9011:9011
```

3.  Add https server to `./nginx/conf/https.conf`

```bash
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name localhosthttps;
    ssl_certificate /etc/nginx/ssl/localhost.pem;
    ssl_certificate_key /etc/nginx/ssl/localhost-key.pem;

    location / {
        proxy_set_header   X-Forwarded-Proto https;
        proxy_set_header   X-Forwarded-Host localhost;
        proxy_set_header   X-Forwarded-Port 9011;
        proxy_http_version 1.1;
        proxy_pass         http://fusionauth:9011;
    }
}
```

5. Generate certificates with mkcert

```bash
mkdir -p nginx/certs
mkcert -install -key-file nginx/certs/localhost-key.pem -cert-file nginx/certs/localhost.pem localhost
```

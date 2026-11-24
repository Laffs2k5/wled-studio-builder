// SPDX-License-Identifier: EUPL-1.2
#pragma once
// spike: the web server's types, as names only (effects never use them)
class AsyncWebServerRequest; class AsyncWebSocket; class AsyncWebSocketClient; class AsyncClient; class AsyncWebServer;
class AsyncResponseStream; class AsyncWebServerResponse; class AsyncWebHandler;
typedef int WebRequestMethodComposite; typedef int AwsEventType; typedef int WiFiEvent_t;
enum { HTTP_GET = 1, HTTP_POST = 2, HTTP_PUT = 4, HTTP_PATCH = 8, HTTP_DELETE = 16, HTTP_ANY = 255 };
#define CONTENT_TYPE_JSON "application/json"

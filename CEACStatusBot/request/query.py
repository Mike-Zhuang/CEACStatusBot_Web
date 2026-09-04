import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin, urlparse

from CEACStatusBot.captcha import CaptchaHandle, OnnxCaptchaHandle


ROOT = "https://ceac.state.gov"
REQUEST_TIMEOUT = (10, 45)
MAX_ATTEMPTS = 5
CEAC_PROVIDER_BLOCKED_ERROR_CODE = "ceac_cloudflare_blocked"


def build_ceac_url(path: str) -> str:
    url = urljoin(ROOT, path)
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "ceac.state.gov":
        raise ValueError("Unexpected CEAC request target")
    return url


def build_failure(error_code, error, attempts, *, detail="", provider_available=False):
    return {
        "success": False,
        "error_code": error_code,
        "error": error,
        "attempts": attempts,
        "detail": detail,
        "provider_available": provider_available,
    }


def extract_page_error(soup):
    candidates = []
    for selector in [
        "#ctl00_ContentPlaceHolder1_ValidationSummary1",
        "#ctl00_ContentPlaceHolder1_lblError",
        ".validation-summary-errors",
        ".field-validation-error",
        ".error",
    ]:
        node = soup.select_one(selector)
        if node:
            text = " ".join(node.get_text(" ", strip=True).split())
            if text:
                candidates.append(text)
    for text in candidates:
        lower = text.lower()
        if "code entered" in lower and "does not match" in lower:
            return "CEAC 验证码校验失败，系统会在下次查询时重新尝试。"
        if "captcha" in lower:
            return "CEAC 验证码校验失败，系统会在下次查询时重新尝试。"
        if "case" in lower or "application" in lower or "passport" in lower or "surname" in lower:
            return "CEAC 提示申请号、护照号、姓氏或办理地点信息不匹配，请核对档案信息。"
        return f"CEAC 返回错误提示：{text[:160]}"
    return ""


def is_cloudflare_blocked(response):
    if response.status_code != 403:
        return False
    server = str(response.headers.get("server", "")).lower()
    body = str(response.text or "").lower()
    return (
        "cloudflare" in server
        or "cf-ray" in {str(key).lower() for key in response.headers}
        or "sorry, you have been blocked" in body
        or "attention required! | cloudflare" in body
    )


def read_span_text(soup, span_id):
    node = soup.find("span", id=span_id)
    return node.get_text(strip=True) if node else ""


def query_status(location, application_num, passport_number, surname, captchaHandle: CaptchaHandle = OnnxCaptchaHandle("captcha.onnx")):
    failCount = 0
    result = {
        "success": False,
    }
    lastFailure = build_failure("unknown", "CEAC 查询失败，请稍后重试。", 0)
    providerAvailable = False
    backupTime = 5

    while failCount < MAX_ATTEMPTS:
        if failCount > 0:
            print(f"Retrying... Attempt {failCount + 1} / {MAX_ATTEMPTS} in {backupTime} seconds")
            time.sleep(backupTime)
        failCount += 1
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Host": "ceac.state.gov",
        }

        session = requests.Session()

        try:
            r = session.get(
                url=build_ceac_url("/ceacstattracker/status.aspx?App=NIV"),
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        except Exception as e:
            print(e)
            lastFailure = build_failure(
                "ceac_initial_request_failed",
                "CEAC 首页请求失败，可能是 CEAC 官网临时不可用、网络波动或服务器出口连接异常。",
                failCount,
                detail=str(e),
            )
            continue

        if is_cloudflare_blocked(r):
            return build_failure(
                CEAC_PROVIDER_BLOCKED_ERROR_CODE,
                "CEAC 当前阻止服务器自动访问，系统已暂停继续重试。这不代表档案信息填写错误。",
                failCount,
                detail="HTTP 403 Cloudflare block",
            )

        soup = BeautifulSoup(r.text, features="lxml")

        # Find captcha image
        captcha = soup.find(name="img", id="c_status_ctl00_contentplaceholder1_defaultcaptcha_CaptchaImage")
        if not captcha or not captcha.get("src"):
            lastFailure = build_failure(
                "ceac_captcha_image_missing",
                "CEAC 页面未返回验证码图片，可能是官网页面结构变化、维护中或被临时拦截。",
                failCount,
            )
            continue
        image_url = build_ceac_url(captcha["src"])
        providerAvailable = True
        try:
            img_resp = session.get(image_url, timeout=REQUEST_TIMEOUT)
        except Exception as e:
            print(e)
            lastFailure = build_failure(
                "ceac_captcha_request_failed",
                "CEAC 验证码图片请求失败，可能是官网临时不可用或网络波动。",
                failCount,
                detail=str(e),
                provider_available=providerAvailable,
            )
            continue
        if is_cloudflare_blocked(img_resp):
            return build_failure(
                CEAC_PROVIDER_BLOCKED_ERROR_CODE,
                "CEAC 当前阻止服务器自动访问，系统已暂停继续重试。这不代表档案信息填写错误。",
                failCount,
                detail="HTTP 403 Cloudflare block",
            )

        # Resolve captcha
        try:
            captcha_num = captchaHandle.solve(img_resp.content)
        except Exception as e:
            print(e)
            lastFailure = build_failure(
                "ceac_captcha_solve_failed",
                "CEAC 验证码识别失败，可能是验证码图片异常或识别模型无法处理当前验证码。",
                failCount,
                detail=str(e),
                provider_available=providerAvailable,
            )
            continue
        print(f"Captcha solved: {captcha_num}")

        # Find the correct value for the location dropdown
        location_dropdown = soup.find("select", id="Location_Dropdown")
        if not location_dropdown:
            lastFailure = build_failure(
                "ceac_location_dropdown_missing",
                "CEAC 页面未返回办理地点下拉框，可能是官网页面结构变化或临时异常。",
                failCount,
                provider_available=providerAvailable,
            )
            continue
        location_value = None
        for option in location_dropdown.find_all("option"):
            if location in option.text:
                location_value = option["value"]
                break

        if not location_value:
            print("Location not found in dropdown options.")
            return build_failure(
                "ceac_location_not_found",
                "CEAC 办理地点匹配失败，请确认档案中选择的办理地点是否仍在 CEAC 官网列表中。",
                failCount,
                provider_available=providerAvailable,
            )

        # Fill form
        def update_from_current_page(cur_page, name, data):
            ele = cur_page.find(name="input", attrs={"name": name})
            if ele:
                data[name] = ele["value"]

        data = {
            "ctl00$ToolkitScriptManager1": "ctl00$ContentPlaceHolder1$UpdatePanel1|ctl00$ContentPlaceHolder1$btnSubmit",
            "ctl00_ToolkitScriptManager1_HiddenField": ";;AjaxControlToolkit, Version=4.1.40412.0, Culture=neutral, PublicKeyToken=28f01b0e84b6d53e:en-US:acfc7575-cdee-46af-964f-5d85d9cdcf92:de1feab2:f9cec9bc:a67c2700:f2c8e708:8613aea7:3202a5a2:ab09e3fe:87104b7c:be6fb298",
            "__EVENTTARGET": "ctl00$ContentPlaceHolder1$btnSubmit",
            "__EVENTARGUMENT": "",
            "__LASTFOCUS": "",
            "__VIEWSTATE": "8GJOG5GAuT1ex7KX3jakWssS08FPVm5hTO2feqUpJk8w5ukH4LG/o39O4OFGzy/f2XLN8uMeXUQBDwcO9rnn5hdlGUfb2IOmzeTofHrRNmB/hwsFyI4mEx0mf7YZo19g",
            "__VIEWSTATEGENERATOR": "DBF1011F",
            "__VIEWSTATEENCRYPTED": "",
            "ctl00$ContentPlaceHolder1$Visa_Application_Type": "NIV",
            "ctl00$ContentPlaceHolder1$Location_Dropdown": location_value,  # Use the correct value
            "ctl00$ContentPlaceHolder1$Visa_Case_Number": application_num,
            "ctl00$ContentPlaceHolder1$Captcha": captcha_num,
            "ctl00$ContentPlaceHolder1$Passport_Number": passport_number,
            "ctl00$ContentPlaceHolder1$Surname": surname,
            "LBD_VCID_c_status_ctl00_contentplaceholder1_defaultcaptcha": "a81747f3a56d4877bf16e1a5450fb944",
            "LBD_BackWorkaround_c_status_ctl00_contentplaceholder1_defaultcaptcha": "1",
            "__ASYNCPOST": "true",
        }

        fields_need_update = [
            "__VIEWSTATE",
            "__VIEWSTATEGENERATOR",
            "LBD_VCID_c_status_ctl00_contentplaceholder1_defaultcaptcha",
        ]
        for field in fields_need_update:
            update_from_current_page(soup, field, data)

        try:
            r = session.post(
                url=build_ceac_url("/ceacstattracker/status.aspx"),
                headers=headers,
                data=data,
                timeout=REQUEST_TIMEOUT,
            )
        except Exception as e:
            print(e)
            lastFailure = build_failure(
                "ceac_submit_request_failed",
                "CEAC 表单提交失败，可能是 CEAC 官网临时不可用、网络波动或服务器出口连接异常。",
                failCount,
                detail=str(e),
                provider_available=providerAvailable,
            )
            continue

        if is_cloudflare_blocked(r):
            return build_failure(
                CEAC_PROVIDER_BLOCKED_ERROR_CODE,
                "CEAC 当前阻止服务器自动访问，系统已暂停继续重试。这不代表档案信息填写错误。",
                failCount,
                detail="HTTP 403 Cloudflare block",
            )

        soup = BeautifulSoup(r.text, features="lxml")
        status_tag = soup.find("span", id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblStatus")
        if not status_tag:
            pageError = extract_page_error(soup)
            lastFailure = build_failure(
                "ceac_status_not_returned",
                pageError or "CEAC 未返回状态结果，可能是验证码识别失败、申请信息不匹配、官网临时异常或页面结构变化。",
                failCount,
                provider_available=providerAvailable,
            )
            continue

        application_num_returned = read_span_text(soup, "ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblCaseNo")
        if application_num_returned != application_num:
            return build_failure(
                "ceac_application_number_mismatch",
                "CEAC 返回的申请号与档案申请号不一致，请核对 Application ID 或 Case Number。",
                failCount,
                provider_available=providerAvailable,
            )
        status = status_tag.get_text(strip=True)
        visa_type = read_span_text(soup, "ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblAppName")
        case_created = read_span_text(soup, "ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblSubmitDate")
        case_last_updated = read_span_text(soup, "ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblStatusDate")
        description = read_span_text(soup, "ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblMessage")
        if not status:
            lastFailure = build_failure(
                "ceac_status_empty",
                "CEAC 返回了状态区域，但状态字段为空，可能是官网页面结构变化或临时异常。",
                failCount,
                provider_available=providerAvailable,
            )
            continue

        result.update({
            "success": True,
            "time": str(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())),
            "visa_type": visa_type,
            "status": status,
            "case_created": case_created,
            "case_last_updated": case_last_updated,
            "description": description,
            "application_num": application_num_returned,
            "application_num_origin": application_num
        })
        break

    return result if result.get("success") else lastFailure

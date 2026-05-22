import ipaddress
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


TEXT_PATTERN = re.compile(r"^[\w\s.,'\`\-:/#()@+|]+$", re.UNICODE)
IDENTIFIER_PATTERN = re.compile(r"^(HAL[A-Z0-9]{6,24}|[A-Z0-9]{6,20})$")
APPLICATION_PATTERN = re.compile(r"^[A-Z0-9\-_ ]{3,40}$")
PASSPORT_PATTERN = re.compile(r"^(NA|[A-Z0-9]{3,32})$")
SURNAME_PATTERN = re.compile(r"^[A-Z]{1,5}$")
KOREA_ENGLISH_NAME_PATTERN = re.compile(r"^[A-Z][A-Z ]{0,78}[A-Z]$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HOST_PATTERN = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")


class SecureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def rejectUnsafeText(value: str, fieldName: str) -> str:
    normalized = value.strip()
    if not TEXT_PATTERN.match(normalized):
        raise ValueError(f"{fieldName} 包含不支持的字符")
    return normalized


def validateSmtpHost(value: str) -> str:
    host = value.strip().lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("SMTP 主机不允许使用本机地址")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        raise ValueError("SMTP 主机必须使用公网域名，不能使用 IP 地址")
    if not HOST_PATTERN.match(host):
        raise ValueError("SMTP 主机必须是合法公网域名")
    return host


class SendCodeRequest(SecureModel):
    email: EmailStr


class PasswordResetCodeRequest(SecureModel):
    email: EmailStr


class PasswordResetRequest(SecureModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)
    password: str = Field(min_length=8)


class RegisterRequest(SecureModel):
    email: EmailStr
    password: str = Field(min_length=8)
    code: str = Field(min_length=4, max_length=12)
    acceptedTerms: bool

    @field_validator("acceptedTerms")
    @classmethod
    def validateAcceptedTerms(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("注册前必须阅读并同意用户条款和免责声明")
        return value


class LoginRequest(SecureModel):
    email: EmailStr
    password: str


class ProfileUpdateRequest(SecureModel):
    email: EmailStr | None = None
    currentPassword: str = Field(min_length=1)
    newPassword: str | None = Field(default=None, min_length=8)


class TimezoneUpdateRequest(SecureModel):
    timezone: str = Field(min_length=1, max_length=80)

    @field_validator("timezone")
    @classmethod
    def validateTimezone(cls, value: str) -> str:
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("时区名称不受支持") from exc
        return normalized


class SmtpConfigInput(SecureModel):
    fromEmail: EmailStr
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    useSsl: bool = True
    password: str = Field(min_length=1)

    @field_validator("host")
    @classmethod
    def validateHost(cls, value: str) -> str:
        return validateSmtpHost(value)

    @field_validator("port")
    @classmethod
    def validatePort(cls, value: int) -> int:
        if value not in {25, 465, 587, 2525}:
            raise ValueError("SMTP 端口不在允许范围内")
        return value


class SystemSmtpConfigInput(SecureModel):
    fromEmail: EmailStr
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    useSsl: bool = True
    password: str | None = None

    @field_validator("host")
    @classmethod
    def validateHost(cls, value: str) -> str:
        return validateSmtpHost(value)

    @field_validator("port")
    @classmethod
    def validatePort(cls, value: int) -> int:
        if value not in {25, 465, 587, 2525}:
            raise ValueError("SMTP 端口不在允许范围内")
        return value


class CeacCaseInput(SecureModel):
    displayName: str = Field(min_length=1, max_length=80)
    location: str = Field(min_length=1, max_length=120)
    applicationNum: str = Field(min_length=1)
    passportNumber: str = Field(min_length=1)
    surname: str = Field(min_length=1, max_length=5)
    receiveEmail: EmailStr | None = None
    senderMode: str = Field(pattern="^(system|custom)$")
    isEnabled: bool = True
    emailNotificationsEnabled: bool = True
    smtpConfig: SmtpConfigInput | None = None

    @field_validator("displayName")
    @classmethod
    def validateDisplayName(cls, value: str) -> str:
        return rejectUnsafeText(value, "档案名称")

    @field_validator("location")
    @classmethod
    def validateLocation(cls, value: str) -> str:
        return rejectUnsafeText(value, "办理地点")

    @field_validator("applicationNum")
    @classmethod
    def validateApplicationNum(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not APPLICATION_PATTERN.match(normalized):
            raise ValueError("Application ID 或 Case Number 格式不支持")
        return normalized

    @field_validator("passportNumber")
    @classmethod
    def validatePassportNumber(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not PASSPORT_PATTERN.match(normalized):
            raise ValueError("护照号码格式不支持")
        return normalized

    @field_validator("surname")
    @classmethod
    def validateSurname(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not SURNAME_PATTERN.match(normalized):
            raise ValueError("姓氏只支持 1-5 个英文字母")
        return normalized

    @field_validator("receiveEmail", mode="before")
    @classmethod
    def normalizeReceiveEmail(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class CeacCasePatch(CeacCaseInput):
    displayName: str | None = Field(default=None, min_length=1, max_length=80)
    location: str | None = Field(default=None, max_length=120)
    applicationNum: str | None = None
    passportNumber: str | None = None
    surname: str | None = Field(default=None, min_length=1, max_length=5)
    receiveEmail: EmailStr | None = None
    senderMode: str | None = Field(default=None, pattern="^(system|custom)$")
    isEnabled: bool | None = None
    emailNotificationsEnabled: bool | None = None
    smtpConfig: SmtpConfigInput | None = None


class IrccApplicationSelection(SecureModel):
    appId: str = Field(min_length=1, max_length=32)
    applicationNumber: str | None = Field(default=None, max_length=64)
    principalApplicant: str | None = Field(default=None, max_length=120)

    @field_validator("appId")
    @classmethod
    def validateAppId(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", normalized):
            raise ValueError("IRCC appId 格式不支持")
        return normalized

    @field_validator("applicationNumber", "principalApplicant")
    @classmethod
    def validateOptionalText(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return rejectUnsafeText(value, "IRCC 申请信息")


class IrccDiscoverRequest(SecureModel):
    portalEmail: EmailStr
    portalPassword: str = Field(min_length=1)


class IrccCaseInput(SecureModel):
    displayName: str = Field(min_length=1, max_length=80)
    portalEmail: EmailStr
    portalPassword: str = Field(min_length=1)
    appId: str = Field(min_length=1, max_length=32)
    applicationNumber: str | None = Field(default=None, max_length=64)
    principalApplicant: str | None = Field(default=None, max_length=120)
    receiveEmail: EmailStr | None = None
    senderMode: str = Field(pattern="^(system|custom)$")
    isEnabled: bool = True
    emailNotificationsEnabled: bool = True
    smtpConfig: SmtpConfigInput | None = None

    @field_validator("displayName")
    @classmethod
    def validateDisplayName(cls, value: str) -> str:
        return rejectUnsafeText(value, "档案名称")

    @field_validator("appId")
    @classmethod
    def validateAppId(cls, value: str) -> str:
        return IrccApplicationSelection.validateAppId(value)

    @field_validator("applicationNumber", "principalApplicant")
    @classmethod
    def validateOptionalText(cls, value: str | None) -> str | None:
        return IrccApplicationSelection.validateOptionalText(value)

    @field_validator("receiveEmail", mode="before")
    @classmethod
    def normalizeReceiveEmail(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class IrccCasePatch(SecureModel):
    displayName: str | None = Field(default=None, min_length=1, max_length=80)
    portalEmail: EmailStr | None = None
    portalPassword: str | None = Field(default=None, min_length=1)
    appId: str | None = Field(default=None, min_length=1, max_length=32)
    applicationNumber: str | None = Field(default=None, max_length=64)
    principalApplicant: str | None = Field(default=None, max_length=120)
    receiveEmail: EmailStr | None = None
    senderMode: str | None = Field(default=None, pattern="^(system|custom)$")
    isEnabled: bool | None = None
    emailNotificationsEnabled: bool | None = None
    smtpConfig: SmtpConfigInput | None = None

    @field_validator("displayName")
    @classmethod
    def validateDisplayName(cls, value: str | None) -> str | None:
        return rejectUnsafeText(value, "档案名称") if value is not None else None

    @field_validator("appId")
    @classmethod
    def validateAppId(cls, value: str | None) -> str | None:
        return IrccApplicationSelection.validateAppId(value) if value is not None else None

    @field_validator("applicationNumber", "principalApplicant")
    @classmethod
    def validateOptionalText(cls, value: str | None) -> str | None:
        return IrccApplicationSelection.validateOptionalText(value)


class KoreaCaseInput(SecureModel):
    displayName: str = Field(min_length=1, max_length=80)
    passportNumber: str = Field(min_length=1)
    englishName: str = Field(min_length=2, max_length=80)
    birthDate: str = Field(min_length=10, max_length=10)
    receiveEmail: EmailStr | None = None
    senderMode: str = Field(pattern="^(system|custom)$")
    isEnabled: bool = True
    emailNotificationsEnabled: bool = True
    smtpConfig: SmtpConfigInput | None = None

    @field_validator("displayName")
    @classmethod
    def validateDisplayName(cls, value: str) -> str:
        return rejectUnsafeText(value, "档案名称")

    @field_validator("passportNumber")
    @classmethod
    def validatePassportNumber(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not PASSPORT_PATTERN.match(normalized):
            raise ValueError("护照号码格式不支持")
        return normalized

    @field_validator("englishName")
    @classmethod
    def validateEnglishName(cls, value: str) -> str:
        normalized = " ".join(value.strip().upper().split())
        if not KOREA_ENGLISH_NAME_PATTERN.match(normalized) or " " not in normalized:
            raise ValueError("英文姓名请按护照填写，先姓后名，拼音大写，姓名中间留空格")
        return normalized

    @field_validator("birthDate")
    @classmethod
    def validateBirthDate(cls, value: str) -> str:
        normalized = value.strip()
        if not DATE_PATTERN.match(normalized):
            raise ValueError("出生日期格式必须为 YYYY-MM-DD")
        return normalized

    @field_validator("receiveEmail", mode="before")
    @classmethod
    def normalizeReceiveEmail(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class KoreaCasePatch(SecureModel):
    displayName: str | None = Field(default=None, min_length=1, max_length=80)
    passportNumber: str | None = None
    englishName: str | None = Field(default=None, min_length=2, max_length=80)
    birthDate: str | None = Field(default=None, min_length=10, max_length=10)
    receiveEmail: EmailStr | None = None
    senderMode: str | None = Field(default=None, pattern="^(system|custom)$")
    isEnabled: bool | None = None
    emailNotificationsEnabled: bool | None = None
    smtpConfig: SmtpConfigInput | None = None

    @field_validator("displayName")
    @classmethod
    def validateDisplayName(cls, value: str | None) -> str | None:
        return rejectUnsafeText(value, "档案名称") if value is not None else None

    @field_validator("passportNumber")
    @classmethod
    def validatePassportNumber(cls, value: str | None) -> str | None:
        return KoreaCaseInput.validatePassportNumber(value) if value is not None else None

    @field_validator("englishName")
    @classmethod
    def validateEnglishName(cls, value: str | None) -> str | None:
        return KoreaCaseInput.validateEnglishName(value) if value is not None else None

    @field_validator("birthDate")
    @classmethod
    def validateBirthDate(cls, value: str | None) -> str | None:
        return KoreaCaseInput.validateBirthDate(value) if value is not None else None


class ProfileOrderItem(SecureModel):
    profileType: str = Field(pattern="^(ceac|ircc|korea)$")
    id: int = Field(ge=1)


class ProfileOrderPatch(SecureModel):
    profiles: list[ProfileOrderItem] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validateUniqueProfiles(self) -> "ProfileOrderPatch":
        seen: set[tuple[str, int]] = set()
        for profile in self.profiles:
            key = (profile.profileType, profile.id)
            if key in seen:
                raise ValueError("档案排序列表包含重复档案")
            seen.add(key)
        return self


class PassportSlotMonitorInput(SecureModel):
    identifier: str = Field(min_length=1, max_length=32)
    isEnabled: bool = True
    emailNotificationsEnabled: bool = True

    @field_validator("identifier")
    @classmethod
    def validateIdentifier(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not IDENTIFIER_PATTERN.match(normalized):
            raise ValueError("UID/HAL 格式不支持")
        return normalized


class PassportSlotMonitorPatch(SecureModel):
    isEnabled: bool | None = None
    emailNotificationsEnabled: bool | None = None


class WorkerPriorityPatch(SecureModel):
    workerPriority: int = Field(ge=1, le=999)


class AccountTierPatch(SecureModel):
    accountTier: str = Field(pattern="^(standard|premium)$")

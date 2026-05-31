import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  HeartHandshake,
  Landmark,
  TreePine,
  Map as LucideMap,
  Mail,
  History,
  LogOut,
  Moon,
  Plus,
  Shield,
  Sun,
  Trash2,
  UserRound,
  User,
  X,
  MapPin,
  FileText,
  Clock,
  Bell,
  FolderOpen,
  Server,
  CloudLightning,
} from "lucide-react";
import { ceacLocations } from "./locations";

type ThemeMode = "dark" | "light";
type LanguageMode = "zh" | "en";
type ViewMode = "dashboard" | "profile" | "admin";
type AuthMode = "login" | "register" | "forgot";
type AccountTier = "standard" | "premium";
type MessageScope = ViewMode | "auth";
type ProfileCountry = "us" | "ca" | "kr";
type QueryTriggerType = "manual" | "automatic" | "passport_slot_manual" | "passport_slot_automatic" | "ircc_manual" | "ircc_automatic" | "korea_manual" | "korea_automatic" | "unknown";

interface User {
  id: number;
  email: string;
  role: "admin" | "user";
  account_tier: AccountTier;
  is_email_verified: number;
  timezone: string;
  created_at: string;
}

interface CeacCase {
  id: number;
  userId: number;
  sortOrder: number;
  displayName: string;
  location: string;
  applicationNum: string;
  passportNumber: string;
  surname: string;
  receiveEmail: string;
  senderMode: "system" | "custom";
  isEnabled: boolean;
  ceacAutoLockedByPassportSlot: boolean;
  ceacConsecutiveErrorCount: number;
  emailNotificationsEnabled: boolean;
  nextCheckAt: string | null;
  lastCheckedAt: string | null;
  lastTriggerType: "manual" | "automatic" | "unknown" | null;
  lastStatus: string | null;
  lastDescription: string | null;
  lastCeacError: string;
  passportSlotMonitor: {
    isEnabled: boolean;
    emailNotificationsEnabled: boolean;
    nextCheckAt: string | null;
    lastCheckedAt: string | null;
    lastSlotCount: number;
    lastResult: {
      slotStatus?: "not_eligible" | "no_slot" | "has_slot" | "unknown";
      statusMessage?: string;
    } | null;
    lastErrorMessage: string;
  } | null;
  createdAt: string;
  updatedAt: string;
}

interface IrccCase {
  id: number;
  userId: number;
  sortOrder: number;
  displayName: string;
  portalEmailMasked: string;
  appId: string;
  applicationNumber: string;
  principalApplicant: string;
  receiveEmail: string;
  senderMode: "system" | "custom";
  isEnabled: boolean;
  emailNotificationsEnabled: boolean;
  nextCheckAt: string | null;
  lastCheckedAt: string | null;
  lastTriggerType: "ircc_manual" | "ircc_automatic" | "unknown" | null;
  lastSnapshotHash: string;
  lastSummary: string;
  lastErrorMessage: string;
  latestSnapshot: IrccSnapshot | null;
  statusOverview: IrccStatusOverview | null;
  createdAt: string;
  updatedAt: string;
}

type IrccStatusTone = "pending" | "approved" | "negative" | "closed" | "unknown";

interface IrccLatestUpdate {
  field: string;
  label: string;
  code: string;
  text: string;
  timeStamp: string | null;
}

interface IrccStatusOverview {
  headlineCode: string;
  headlineText: string;
  tone: IrccStatusTone;
  overallCode: string;
  overallText: string;
  latestUpdate: IrccLatestUpdate | null;
}

interface KoreaCase {
  id: number;
  userId: number;
  sortOrder: number;
  displayName: string;
  passportNumber: string;
  englishName: string;
  birthDate: string;
  receiveEmail: string;
  senderMode: "system" | "custom";
  isEnabled: boolean;
  emailNotificationsEnabled: boolean;
  nextCheckAt: string | null;
  lastCheckedAt: string | null;
  lastTriggerType: "korea_manual" | "korea_automatic" | "unknown" | null;
  lastSnapshotHash: string;
  lastApplicationNo: string;
  lastApplicationDate: string;
  lastEntryPurpose: string;
  lastStatus: string;
  lastErrorMessage: string;
  createdAt: string;
  updatedAt: string;
}

interface IrccSnapshot {
  applicationInfo?: Record<string, unknown>;
  appStatus?: Record<string, unknown>;
  messages?: Array<Record<string, unknown>>;
}

type ProfileListItem =
  | { profileType: "ceac"; id: number; sortOrder: number; updatedAt: string; case: CeacCase }
  | { profileType: "ircc"; id: number; sortOrder: number; updatedAt: string; case: IrccCase }
  | { profileType: "korea"; id: number; sortOrder: number; updatedAt: string; case: KoreaCase };

interface IrccHistoryItem {
  id: number;
  caseId: number;
  snapshotHash: string;
  applicationStatus: string;
  applicationInfoStatus: string;
  messageCount: number;
  changeSummary: string;
  fetchedAt: string;
  rawPayload: IrccSnapshot;
  notificationSent: boolean;
}

interface KoreaHistoryItem {
  id: number;
  caseId: number;
  snapshotHash: string;
  applicationNo: string;
  applicationDate: string;
  entryPurpose: string;
  status: string;
  fetchedAt: string;
  rawPayload: Record<string, unknown>;
  notificationSent: boolean;
}

interface IrccDiscoveredApplication {
  appId: string;
  applicationNumber: string;
  principalApplicant: string;
  status: string;
  submittedAt: string;
}

interface HistoryItem {
  id: number;
  caseId: number;
  status: string;
  description: string;
  ceacLastUpdated: string;
  visaType: string;
  caseCreated: string;
  fetchedAt: string;
}

interface QueryRun {
  id: number;
  case_id: number;
  display_name: string;
  application_num: string;
  user_email: string;
  started_at: string;
  finished_at: string;
  trigger_type: QueryTriggerType;
  success: number;
  status: string | null;
  error_message: string;
  duration_ms: number;
  profile_type?: "ceac" | "ircc" | "korea" | "passport_slot";
}

interface AdminQueryJob {
  id: number;
  case_id: number;
  display_name: string;
  application_num: string;
  user_email: string;
  worker_priority: number;
  queue_position: number;
  trigger_type: QueryTriggerType;
  status: "queued" | "running";
  attempts: number;
  locked_by: string | null;
  created_at: string;
  started_at: string | null;
  updated_at: string;
  wait_seconds: number;
  profile_type?: "ceac" | "ircc" | "korea";
}

interface AdminScheduledQueryJob {
  scheduled_id: string;
  case_id: number;
  display_name: string;
  application_num: string;
  user_email: string;
  worker_priority: number;
  schedule_position: number;
  trigger_type: QueryTriggerType;
  next_check_at: string;
  seconds_until_queue: number;
  profile_type?: "ceac" | "ircc" | "korea";
}

interface AdminFinishedQueryJob {
  id: number;
  case_id: number;
  display_name: string;
  application_num: string;
  user_email: string;
  worker_priority: number;
  finished_position: number;
  trigger_type: QueryTriggerType;
  status: "succeeded" | "failed";
  error_message: string;
  locked_by: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string;
  duration_seconds: number;
  profile_type?: "ceac" | "ircc" | "korea";
}

interface QueryJob {
  id: number;
  caseId: number;
  triggerType: "manual" | "automatic" | "passport_slot_manual" | "passport_slot_automatic";
  status: "queued" | "running" | "succeeded" | "failed";
  attempts: number;
  errorMessage: string;
  result: {
    success: boolean;
    changed: boolean;
    error: string;
    slotStatus?: "not_eligible" | "no_slot" | "has_slot" | "unknown";
    slotCount?: number;
    notified?: boolean;
  } | null;
  createdAt: string;
  updatedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}

interface IrccQueryJob {
  id: number;
  caseId: number;
  triggerType: "ircc_manual" | "ircc_automatic";
  status: "queued" | "running" | "succeeded" | "failed";
  attempts: number;
  errorMessage: string;
  result: {
    success: boolean;
    changed: boolean;
    error: string;
    summary?: string;
  } | null;
  createdAt: string;
  updatedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}

interface KoreaQueryJob {
  id: number;
  caseId: number;
  triggerType: "korea_manual" | "korea_automatic";
  status: "queued" | "running" | "succeeded" | "failed";
  attempts: number;
  errorMessage: string;
  result: {
    success: boolean;
    changed: boolean;
    error: string;
    result?: Record<string, unknown>;
  } | null;
  createdAt: string;
  updatedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}

interface PassportSlotMonitor {
  id: number;
  caseId: number;
  identifier: string;
  identifierMasked: string;
  isEnabled: boolean;
  emailNotificationsEnabled: boolean;
  nextCheckAt: string | null;
  lastCheckedAt: string | null;
  lastSlotFingerprint: string;
  lastSlotCount: number;
  lastResult: {
    success?: boolean;
    availableSlots?: unknown[];
    availableDates?: unknown[];
    slotStatus?: "not_eligible" | "no_slot" | "has_slot" | "unknown";
    statusMessage?: string;
    hasSlotStableCount?: number;
    raw?: unknown;
    error?: string;
  } | null;
  lastErrorMessage: string;
  createdAt: string;
  updatedAt: string;
}

interface PassportSlotHistoryItem {
  id: number;
  caseId: number;
  slotFingerprint: string;
  slotCount: number;
  rawPayload: Record<string, unknown>;
  fetchedAt: string;
  notificationSent: boolean;
}

interface AdminUser {
  id: number;
  email: string;
  role: "admin" | "user";
  account_tier: AccountTier;
  worker_priority: number;
  is_email_verified: number;
  created_at: string;
  updated_at: string;
  case_count: number;
  last_checked_at: string | null;
}

interface AdminCase extends CeacCase {
  profileType?: "ceac" | "ircc" | "korea";
  adminCaseKey?: string;
  appId?: string;
  applicationNumber?: string;
  principalApplicant?: string;
  statusOverview?: IrccStatusOverview | null;
}

interface SecurityEvent {
  id: number;
  event_type: string;
  severity: "info" | "warning" | "error";
  user_id: number | null;
  user_email: string | null;
  email_hash: string;
  ip_hash: string;
  device_hash: string;
  actor_summary: string;
  path: string;
  detail: string;
  created_at: string;
}

interface EmailDeliveryLog {
  id: number;
  user_id: number;
  user_email: string;
  case_id: number | null;
  display_name: string;
  email_type: string;
  recipient: string;
  subject: string;
  body: string;
  created_at: string;
}

interface SystemEmailConfig {
  fromEmail: string;
  host: string;
  port: number;
  useSsl: boolean;
  source: "database" | "environment";
  isConfigured: boolean;
  hasPassword: boolean;
}

interface SystemEmailForm {
  fromEmail: string;
  host: string;
  port: string;
  useSsl: boolean;
  password: string;
}

interface ProfileForm {
  email: string;
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
}

interface CaseForm {
  displayName: string;
  location: string;
  applicationNum: string;
  passportNumber: string;
  surname: string;
  receiveEmail: string;
  senderMode: "system" | "custom";
  isEnabled: boolean;
  emailNotificationsEnabled: boolean;
  smtpFromEmail: string;
  smtpHost: string;
  smtpPort: string;
  smtpUseSsl: boolean;
  smtpPassword: string;
}

interface IrccCaseForm {
  displayName: string;
  portalEmail: string;
  portalPassword: string;
  appId: string;
  applicationNumber: string;
  principalApplicant: string;
  receiveEmail: string;
  senderMode: "system" | "custom";
  isEnabled: boolean;
  emailNotificationsEnabled: boolean;
  smtpFromEmail: string;
  smtpHost: string;
  smtpPort: string;
  smtpUseSsl: boolean;
  smtpPassword: string;
}

interface KoreaCaseForm {
  displayName: string;
  passportNumber: string;
  englishName: string;
  birthDate: string;
  receiveEmail: string;
  senderMode: "system" | "custom";
  isEnabled: boolean;
  emailNotificationsEnabled: boolean;
  smtpFromEmail: string;
  smtpHost: string;
  smtpPort: string;
  smtpUseSsl: boolean;
  smtpPassword: string;
}

const emptyCaseForm: CaseForm = {
  displayName: "",
  location: "CHINA, BEIJING",
  applicationNum: "",
  passportNumber: "",
  surname: "",
  receiveEmail: "",
  senderMode: "system",
  isEnabled: true,
  emailNotificationsEnabled: true,
  smtpFromEmail: "",
  smtpHost: "smtp.exmail.qq.com",
  smtpPort: "465",
  smtpUseSsl: true,
  smtpPassword: "",
};

const emptyIrccCaseForm: IrccCaseForm = {
  displayName: "",
  portalEmail: "",
  portalPassword: "",
  appId: "",
  applicationNumber: "",
  principalApplicant: "",
  receiveEmail: "",
  senderMode: "system",
  isEnabled: true,
  emailNotificationsEnabled: true,
  smtpFromEmail: "",
  smtpHost: "smtp.exmail.qq.com",
  smtpPort: "465",
  smtpUseSsl: true,
  smtpPassword: "",
};

const emptyKoreaCaseForm: KoreaCaseForm = {
  displayName: "",
  passportNumber: "",
  englishName: "",
  birthDate: "",
  receiveEmail: "",
  senderMode: "system",
  isEnabled: true,
  emailNotificationsEnabled: true,
  smtpFromEmail: "",
  smtpHost: "smtp.exmail.qq.com",
  smtpPort: "465",
  smtpUseSsl: true,
  smtpPassword: "",
};

function createEmptyCaseForm(defaultEmail = ""): CaseForm {
  return { ...emptyCaseForm, receiveEmail: defaultEmail };
}

function createEmptyIrccCaseForm(defaultEmail = ""): IrccCaseForm {
  return { ...emptyIrccCaseForm, receiveEmail: defaultEmail };
}

function createEmptyKoreaCaseForm(defaultEmail = ""): KoreaCaseForm {
  return { ...emptyKoreaCaseForm, receiveEmail: defaultEmail };
}

const icpRecordNumber = import.meta.env.VITE_ICP_RECORD_NUMBER as string | undefined;
const QUERY_JOB_POLL_INTERVAL_MS = 2000;
const QUERY_JOB_QUEUE_WAIT_MS = 180000;
const ADMIN_QUEUE_REFRESH_INTERVAL_MS = 3000;
const USER_TERMS_VERSION_LABEL = "2026-05-15";

const legalTerms = {
  en: [
    {
      title: "1. Nature of Service and Non-official Status",
      body: [
        "CEACStatusBot is a nonprofit personal project for learning, research, and convenience tooling for the site owner and authorized users. It is not affiliated with, endorsed by, sponsored by, or operated by the U.S. Department of State, CEAC, GTS, CITIC Bank, IRCC, Korea Visa Portal, the Government of Canada, the Ministry of Justice of Korea, any consulate, embassy, visa center, or other official institution.",
        "This site does not provide visa agency services, official appointment services, legal services, immigration consulting, paid official processing, automatic booking, slot holding, or slot grabbing.",
      ],
    },
    {
      title: "2. User Authorization and Required Information",
      body: [
        "By registering, creating a profile, or enabling monitoring, you confirm that you are the data subject or have obtained lawful authorization from the data subject, and you authorize this site to process the information you submit only for CEAC status checking, GTS slot detection, IRCC Portal status checking, Korea Visa Portal status checking, email notification, account operation, abuse prevention, security audit, and necessary maintenance.",
        "You are responsible for the accuracy, legality, and authorization status of Application ID / Case Number, passport number, surname initials, UID/HAL, IRCC Portal credentials, Korea visa passport number, English name, date of birth, email address, and related information submitted by you.",
      ],
    },
    {
      title: "3. Cross-border Query Authorization",
      body: [
        "You understand and agree that, to perform CEAC status checks, GTS slot detection, and IRCC Portal status checks, this site may submit necessary profile information, including but not limited to Application ID / Case Number, passport number, surname initials, UID/HAL, IRCC Portal credentials, Korea visa passport number, English name, date of birth, tokens, appId, and related query parameters, to CEAC, GTS, IRCC Portal, Korea Visa Portal, and other official or third-party systems that may be located outside mainland China.",
        "Such transmission is performed only for the query functions you enable or manually trigger. If you do not agree to this cross-border query processing, do not create a profile, enable monitoring, or use the query features.",
      ],
    },
    {
      title: "4. Third-party Dependence and No Guarantee",
      body: [
        "CEAC, GTS, and IRCC Portal are independent third-party websites. Query results may be delayed, unavailable, incomplete, blocked, changed, or incorrect because of third-party maintenance, network conditions, CAPTCHA recognition, rate limits, interface changes, authentication requirements, or user input errors.",
        "This site does not guarantee visa results, passport progress, CEAC status accuracy, slot availability, booking success, query timeliness, uninterrupted service, or that any notification will be received before a slot changes or disappears.",
      ],
    },
    {
      title: "5. Prohibited Conduct",
      body: [
        "You must not attack, probe, scrape, overload, bypass limits, abuse APIs, submit another person's information without authorization, use automated clients outside the provided website, interfere with other users, attempt unauthorized access, or use this site for unlawful, fraudulent, commercial resale, or rights-infringing purposes.",
        "The administrator may limit, suspend, terminate, delete, or refuse service for accounts, devices, IP addresses, or traffic patterns that appear abusive, risky, unlawful, or harmful to system stability.",
      ],
    },
    {
      title: "6. Data Protection, Retention, and User Responsibility",
      body: [
        "Sensitive profile fields, UID/HAL, IRCC Portal credentials and tokens, SMTP secrets, and raw query snapshots are encrypted at rest where supported by the application. The site also uses rate limits, session controls, security logs, and other protective measures, but no online system can be guaranteed to be absolutely secure.",
        "To reduce long-term retention of personal information, if an account has no new CEAC status history, GTS slot-change history, or IRCC status history, Korea visa status history for about 15 days, the site may send a deletion warning. If there is still no new status or slot activity for about another 15 days, meaning about 30 days in total, the account and related profile data may be automatically deleted.",
        "You should keep your account password, UID/HAL, passport information, screenshots, emails, and notification content confidential. Do not forward or publicly post emails or screenshots containing personal or passport-related information.",
      ],
    },
    {
      title: "7. Service Changes, Limits, and Suspension",
      body: [
        "The site may adjust polling frequency, quotas, worker priority, notification behavior, security rules, supported features, or availability at any time for compliance, stability, cost control, anti-abuse, third-party limitations, or maintenance needs.",
        "Nonprofit support or Premium status is not a purchase of official service and does not create any guarantee regarding official systems, visa outcomes, passport delivery, appointment slots, or booking results.",
      ],
    },
    {
      title: "8. Limitation of Liability and Contact",
      body: [
        "To the maximum extent permitted by applicable law, the site owner is not liable for losses caused by third-party website behavior, query failures, delayed or missed notifications, user input errors, unauthorized use of another person's information, account compromise, service interruption, or reliance on the displayed results.",
        "For questions, security reports, account issues, or removal requests, contact ceac-admin@mikezhuang.cn.",
      ],
    },
  ],
  zh: [
    {
      title: "一、服务性质与非官方声明",
      body: [
        "CEACStatusBot 是非盈利个人项目，主要用于学习研究，以及为站长和经授权用户提供公开状态查询的便利工具。本站不隶属于美国国务院、CEAC、GTS、中信银行、IRCC、韩国签证门户、加拿大政府、韩国法务部、任何使领馆、签证中心或其他官方机构，也不代表上述机构提供服务。",
        "本站不提供签证代理、官方预约、法律服务、移民咨询、有偿官方代办、自动预约、自动占位或抢 slot 服务。",
      ],
    },
    {
      title: "二、用户授权与必要信息",
      body: [
        "你注册、创建档案或启用监控，即确认你本人为相关信息主体，或已取得信息主体的合法授权；你授权本站仅为 CEAC 状态查询、GTS slot 检测、IRCC Portal 状态查询、韩国签证门户状态查询、邮件通知、账号管理、防滥用、安全审计和必要维护处理你提交的信息。",
        "你应自行确保提交的 Application ID / Case Number、护照号、姓氏前几位、UID/HAL、IRCC Portal 凭证、韩国签证护照号、英文姓名、出生日期、邮箱和其他信息真实、准确、合法且已获授权。",
      ],
    },
    {
      title: "三、跨境查询授权",
      body: [
        "你理解并同意，为执行 CEAC 状态查询、GTS slot 检测和 IRCC Portal 状态查询、韩国签证门户状态查询，本站可能将必要的档案信息，包括但不限于 Application ID / Case Number、护照号、姓氏前几位、UID/HAL、IRCC Portal 凭证、韩国签证护照号、英文姓名、出生日期、token、appId 及相关查询参数，提交至 CEAC、GTS、IRCC Portal、韩国签证门户 或其他可能位于中国大陆境外的官方或第三方系统。",
        "上述传输仅用于你启用或手动触发的查询功能。如果你不同意此类跨境查询处理，请不要创建档案、启用监控或使用查询功能。",
      ],
    },
    {
      title: "四、第三方依赖与不保证事项",
      body: [
        "CEAC、GTS 和 IRCC Portal 均为独立第三方网站。查询结果可能因第三方维护、网络波动、验证码识别、接口限流、页面结构变化、登录验证要求或用户输入错误而延迟、不可用、不完整、被拦截或不准确。",
        "本站不保证签证结果、护照进度、CEAC 状态准确性、slot 可用性、预约成功、查询时效、服务不中断，也不保证任何提醒一定早于 slot 变化或消失送达。",
      ],
    },
    {
      title: "五、禁止行为",
      body: [
        "你不得攻击、探测、爬取、压测、绕过限流、滥用接口、未经授权提交他人信息、使用站外自动化客户端、干扰其他用户、尝试未授权访问，或将本站用于违法违规、欺诈、商业转售、侵权等目的。",
        "如账号、设备、IP 或流量行为存在滥用、风险、违法嫌疑或影响系统稳定，管理员有权限制、暂停、终止、删除或拒绝提供服务。",
      ],
    },
    {
      title: "六、数据保护、保留期限与用户责任",
      body: [
        "在应用支持范围内，CEAC 档案敏感字段、UID/HAL、IRCC Portal 凭证和 token、SMTP 密钥和原始查询快照会进行加密存储；本站也会使用限流、会话控制、安全日志等措施降低风险，但任何在线系统都无法承诺绝对安全。",
        "为减少个人信息长期保存风险，如果普通账号约 15 天没有新的 CEAC 状态历史、GTS slot 变化历史、IRCC 状态历史、韩国签证状态历史或对应查询运行记录，系统可能发送删除提醒；提醒后约 15 天仍无新的状态、slot 动态或查询运行记录，即总计约 30 天无动态时，系统可能自动删除该账号和相关档案数据。管理员账号不适用这条自动删除规则。",
        "你应妥善保管账号密码、UID/HAL、护照信息、截图、邮件和通知内容，不应转发或公开包含个人信息、护照信息或预约识别信息的邮件和截图。",
      ],
    },
    {
      title: "七、服务调整、限额与暂停",
      body: [
        "出于合规、稳定性、成本控制、防滥用、第三方限制或维护需要，本站可随时调整查询频率、账号额度、Worker 优先级、通知策略、安全规则、功能范围或服务可用性。",
        "自愿赞赏或 Premium 状态不构成购买官方服务，也不形成对官方系统、签证结果、护照送达、slot 可用性或预约成功的任何保证。",
      ],
    },
    {
      title: "八、责任限制与联系方式",
      body: [
        "在适用法律允许的最大范围内，站长不对第三方网站行为、查询失败、通知延迟或未送达、用户输入错误、未经授权使用他人信息、账号泄露、服务中断或用户依赖页面结果造成的损失承担责任。",
        "如需咨询、反馈安全问题、处理账号事项或请求删除信息，请联系 ceac-admin@mikezhuang.cn。",
      ],
    },
  ],
} as const;

const translations = {
  en: {
    admin: "Admin",
    adminTitle: "Admin Console",
    adminUsers: "Users",
    accountTier: "Account tier",
    accountTierStandard: "Standard",
    accountTierPremium: "Premium",
    accountTierSaved: "Account tier saved.",
    accountTierLimits: "Standard: 1 profile with automatic CEAC checks about once per hour; after Issued, checks slow to once per day and stop after one week. Manual refresh is limited to 1/day, with limited daily emails. Premium: 5 profiles with higher query and email quotas.",
    accountTierCurrent: "Current tier",
    appSubtitle: "Visa status monitoring, query history, and email delivery.",
    publicNoticeTitle: "Service notice",
    publicNoticeBody: "CEACStatusBot is a non-official, nonprofit personal project for learning, research, and convenient status checking by the site owner and authorized users. It is not affiliated with the U.S. Department of State, CEAC, GTS, CITIC Bank, IRCC, Korea Visa Portal, the Government of Canada, or the Ministry of Justice of Korea.",
    publicNoticeDisclaimer: "This site does not provide visa agency services, official appointment services, immigration consulting, automatic booking, slot holding, result guarantees, or any official government or bank service. Query results depend on third-party websites and may be delayed, unavailable, incomplete, or incorrect.",
    acceptTerms: "I have read and agree to the Terms of Use and Disclaimer.",
    termsTitle: "Terms of Use and Disclaimer",
    termsBody: "Please review the full terms before creating an account. Registration means you confirm authorization to submit the information, accept the non-official and nonprofit nature of this service, and understand the third-party and no-guarantee limitations.",
    termsVersion: "Version",
    viewTerms: "View and accept full terms",
    closeTerms: "Close terms",
    profileTermsIntro: "You can review the current Terms of Use and Disclaimer here at any time. Opening the full terms while signed in records acceptance of the current version.",
    applicationId: "Application ID or Case Number",
    autoMonitor: "Enable automatic monitoring",
    caseCreated: "Visa profile created.",
    caseList: "Profiles",
    caseName: "Profile name",
    caseNamePlaceholder: "e.g. Beijing F1 interview",
    casesOwned: "Profiles",
    changeContent: "Change",
    confirmDelete: "Delete this profile?",
    createdAt: "Created",
    currentLogin: "Signed in as",
    dashboard: "My Profiles",
    deliveryEmail: "Notification email",
    deliverySection: "Email delivery",
    emailDeliveryLogs: "Email delivery logs",
    emailDeliveryEmptyBody: "Body was not recorded for this earlier email.",
    emailType: "Email type",
    recipient: "Recipient",
    subject: "Subject",
    body: "Body",
    duration: "Duration",
    email: "Email",
    emailPushOff: "Email updates off",
    emailPushOn: "Email updates on",
    emailPushSetting: "Send email when status changes",
    error: "Failed",
    executor: "User",
    fastQuery: "Query now",
    fastQueryChanged: "Query completed: status changed",
    fastQueryUnchanged: "Query completed: status unchanged",
    firstFiveSurname: "First 5 Letters of Surname",
    firstFiveSurnameHint: "Enter only the first 5 letters of your surname. If shorter, enter the full surname.",
    forgotPassword: "Forgot password?",
    lastCheckMode: "Last query mode",
    lastCheckedAt: "Last updated",
    lastCeacError: "Latest CEAC query issue",
    ceacConsecutiveErrors: "Consecutive CEAC failures",
    lastQuery: "Last query",
    location: "Select a location",
    locationMetric: "Location",
    keepPasswordPlaceholder: "Leave blank to keep current password",
    login: "Sign in",
    loginAction: "Sign in",
    logItems: "logs",
    logoutTitle: "Sign out",
    missingCaseNumber: "No case number",
    noCases: "No profiles yet",
    noHistory: "No status history yet",
    noLogs: "No logs yet",
    noStatus: "Not ready",
    noStatusChange: "No status change",
    notificationSent: "Notification sent",
    notificationNotSent: "No notification sent",
    moveProfileUp: "Move up",
    moveProfileDown: "Move down",
    profileOrderSaved: "Profile order saved.",
    profileOrderFailed: "Failed to save profile order.",
    issuedSlowQueryNotice: "This profile is Issued. Automatic checks are now daily and will stop automatically after one week if you do not stop them here.",
    stopAutomaticQuery: "Stop automatic checks",
    startAutomaticQuery: "Start automatic checks",
    automaticQueryStopped: "Automatic checks stopped. You can still query manually.",
    automaticQueryStarted: "Automatic checks resumed. The next query has been scheduled.",
    notVerified: "Not verified",
    newProfile: "New",
    nextCheckAt: "Next automatic query",
    notifyEmail: "Notification email",
    officialIntro: "Welcome! On this website, you can check your U.S. visa application status.",
    passport: "Passport Number",
    passportPlaceholder: "Passport Number or NA",
    password: "Password",
    passwordOrCode: "Password / App password",
    personalInfo: "Account",
    profile: "Profile",
    profileSaved: "Account updated.",
    refresh: "Refresh",
    register: "Register",
    registerAction: "Create account",
    rememberLogin: "Remember email and password",
    rememberAccount: "Remember email",
    rememberPassword: "Remember password",
    rememberPasswordWarning: "Only use this on a private device. The password is stored in this browser.",
    resetAction: "Reset password",
    resetCodeSent: "If this email exists, a reset code has been sent.",
    resetPassword: "Reset password",
    resetPasswordSaved: "Password has been reset. Please sign in.",
    resetPasswordMismatch: "The two passwords do not match.",
    requestFailed: "Request failed",
    save: "Save profile",
    send: "Send",
    sendCodeFailed: "Failed to send verification code",
    senderConfig: "Sender configuration",
    securityEvents: "Security events",
    securityActor: "Actor",
    securityEventType: "Event",
    securitySeverity: "Severity",
    signInFailed: "Operation failed",
    smtpEmail: "Sender email",
    smtpHost: "SMTP server",
    smtpPort: "SMTP port",
    status: "Status",
    statusHistory: "Status history",
    statusMonitoring: "Visa Status Check",
    success: "Success",
    irccSnapshotSaved: "Snapshot saved",
    systemLogs: "System query logs",
    workerQueue: "Worker queue",
    workerQueueEmpty: "No queued or running jobs",
    workerScheduledQueue: "Upcoming scheduled jobs",
    workerScheduledQueueEmpty: "No upcoming automatic jobs",
    workerFinishedQueue: "Recently left queue",
    workerFinishedQueueEmpty: "No recently finished jobs",
    workerQueueCurrent: "Current queue / running",
    scheduledPosition: "Upcoming position",
    expectedQueueAt: "Expected queue time",
    timeUntilQueue: "Time until queue",
    finishedAt: "Finished",
    queuePosition: "Position",
    queueWait: "Wait",
    workerStatus: "Job status",
    workerLockedBy: "Worker",
    systemEmail: "Default sender email",
    systemEmailConfigured: "Configured",
    systemEmailNotConfigured: "Not configured",
    systemEmailSaved: "Default sender email saved.",
    systemEmailSource: "Source",
    systemSender: "System sender",
    testEmail: "Test email",
    testEmailSending: "Sending current status email.",
    testEmailSent: "Test email sent with the current status template.",
    themeToDark: "Switch to dark mode",
    themeToLight: "Switch to light mode",
    updatePushDisabled: "Status update emails disabled.",
    updatePushEnabled: "Status update emails enabled.",
    updatedAt: "Updated",
    useCustomSmtp: "Custom SMTP",
    useSsl: "Use SSL",
    triggerAutomatic: "Automatic",
    triggerManual: "Manual",
    triggerUnknown: "Unknown",
    verificationCode: "Verification code",
    verificationCodeSent: "Verification code sent. Please check your mailbox.",
    verified: "Verified",
    visaApplicationType: "Visa Application Type",
    visaTypeNiv: "Nonimmigrant Visa (NIV)",
    waitFirstQuery: "Waiting for first query",
    queryHint: "Please select a location and enter your Application ID or Case Number.",
    queryQueued: "Your query is queued because another task is being processed. The task ahead should finish soon, and your query will start automatically. Please do not click repeatedly.",
    queryInProgress: "Querying CEAC. Please wait.",
    pre2022Note: "NOTE: For applicants who completed their forms prior to January 1, 2022, please put NA into the Passport and Surname fields.",
    passportSlotMonitor: "Passport appointment monitor",
    passportSlotIntro: "Enter your UID or HAL after Approved or Issued to watch GTS appointment slots.",
    passportSlotEarlyHint: "You can configure this now, but GTS usually returns valid tokens after Approved or Issued.",
    passportSlotDetectionOnly: "This monitor detects GTS appointment slots returned by the official site and sends notifications. It does not automatically book, hold, or grab slots, and does not guarantee completeness, real-time accuracy, or booking success.",
    passportSlotIdentifier: "UID or HAL",
    passportSlotIdentifierPlaceholder: "106417002 or HAL0123456789",
    passportSlotSave: "Save monitor",
    passportSlotSaved: "Passport appointment monitor saved.",
    passportSlotEnabled: "GTS monitor enabled.",
    passportSlotDisabled: "GTS monitor disabled.",
    passportSlotEmailEnabled: "GTS slot email notifications enabled.",
    passportSlotEmailDisabled: "GTS slot email notifications disabled.",
    passportSlotBookedStop: "I booked, stop monitor",
    passportSlotBookedStopped: "Passport appointment monitor stopped. Email settings and history are kept.",
    passportSlotManualQuery: "Check slots now",
    passportSlotTestEmail: "Test GTS email",
    passportSlotTestEmailSending: "Sending GTS monitor test email.",
    passportSlotTestEmailSent: "GTS monitor test email sent.",
    passportSlotQueued: "Your GTS slot query is queued because another task is being processed. The task ahead should finish soon, and your query will start automatically. Please do not click repeatedly.",
    passportSlotQuerying: "Querying GTS slots. Please wait.",
    passportSlotFound: "GTS slot query completed: available slots found.",
    passportSlotNotFound: "GTS slot query completed: no available slot.",
    passportSlotChanged: "GTS slot result changed.",
    passportSlotConfigured: "Configured identifier",
    passportSlotCurrentStatus: "Current GTS status",
    passportSlotNotEligible: "Not eligible for passport appointment yet.",
    passportSlotNoSlot: "Eligible, but no available slot.",
    passportSlotStatusHasSlot: "Available slots found.",
    passportSlotLastCount: "Last slot count",
    passportSlotLastError: "Last GTS error",
    passportSlotHistory: "Slot change history",
    ceacAutoLockedByPassportSlot: "CEAC automatic checks were stopped because GTS indicates the passport is ready for appointment. Only an admin can restore CEAC automatic checks.",
    restoreCeacAutoQuery: "Restore CEAC auto checks",
    ceacAutoQueryRestored: "CEAC automatic checks restored.",
    supportTitle: "Support this nonprofit project",
    supportBody: "If CEACStatusBot helps you, voluntary support helps cover server and maintenance costs.",
    supportPremium: "Premium upgrade: share a Xiaohongshu post with the site link, screenshots, and your experience, then contact the admin; or leave your account email in the donation note for manual review.",
    supportDisclaimer: "Non-official service. Not affiliated with the U.S. Department of State, CEAC, GTS, CITIC Bank, IRCC, Korea Visa Portal, the Government of Canada, or the Ministry of Justice of Korea. Donations are voluntary support, not a purchase of official services, and do not guarantee visa results, passport progress, slot availability, or booking success. Do not publicly share screenshots containing UID/HAL/passport/IRCC/Korea visa data.",
    nonprofitNotice: "Nonprofit personal project",
    contactEmail: "Contact: ceac-admin@mikezhuang.cn",
    sourceCode: "Source code",
    workerPriority: "Worker priority",
    workerPriorityHint: "Smaller number runs earlier. Premium defaults to 50; Standard defaults to 100.",
    saveWorkerPriority: "Save priority",
    workerPrioritySaved: "Worker priority saved.",
    noPassportSlotMonitor: "No UID/HAL monitor yet",
    noPassportSlotHistory: "No slot changes yet",
    country: "Country",
    countryUnitedStates: "United States",
    countryCanada: "Canada",
    countryKorea: "South Korea",
    koreaVisaTitle: "Korea Visa Portal",
    koreaQueryHint: "Consular office + passport number query. Enter the English name exactly as on the passport.",
    koreaEnglishName: "English name",
    koreaNameHint: "Surname first, given name after it, uppercase pinyin, with a space between names.",
    koreaBirthDate: "Date of birth",
    koreaApplicationNo: "Application no.",
    koreaApplicationDate: "Application date",
    koreaEntryPurpose: "Entry purpose",
    koreaProgressStatus: "Progress status",
    koreaSave: "Save Korea profile",
    koreaQuerying: "Querying Korea Visa Portal. Please wait.",
    koreaQueued: "Your Korea visa query is queued.",
    koreaChanged: "Korea visa query completed: status changed.",
    koreaUnchanged: "Korea visa query completed: status unchanged.",
    koreaTestEmail: "Test Korea email",
    koreaTestEmailSending: "Sending Korea visa test email.",
    koreaTestEmailSent: "Korea visa test email sent.",
    koreaLastError: "Latest Korea visa issue",
    koreaNoHistory: "No Korea visa history yet",
    irccAlphaLabel: "Alpha",
    irccPortalTitle: "IRCC Portal monitor",
    irccPortalIntro: "Alpha: only the current IRCC Portal is supported. Use carefully; IRCC Portal - New version and GCKey are planned for the future.",
    irccPortalEmail: "IRCC Portal email",
    irccPortalPassword: "IRCC Portal password",
    irccDiscoverApplications: "Find submitted applications",
    irccApplicationFound: "Applications found. Select one or enter appId manually.",
    irccApplicationSelect: "Submitted application",
    irccAppId: "IRCC appId",
    irccApplicationNumber: "Application number",
    irccPrincipalApplicant: "Principal applicant",
    irccSave: "Save IRCC profile",
    irccQuerying: "Querying IRCC Portal. Please wait.",
    irccQueued: "Your IRCC query is queued.",
    irccChanged: "IRCC query completed: snapshot changed.",
    irccUnchanged: "IRCC query completed: snapshot unchanged.",
    irccTestEmail: "Test IRCC email",
    irccTestEmailSending: "Sending IRCC test email.",
    irccTestEmailSent: "IRCC test email sent.",
    irccApplicationStatus: "Application status",
    irccStatusOverview: "Current status overview",
    irccOverallStatus: "Overall status",
    irccLatestUpdate: "Latest update",
    irccApplicantInfo: "Applicant information",
    irccMessages: "Messages",
    irccGhostUpdate: "Home updated time comes from the submitted applications page. If it changes while the detail page stays the same, it is recorded as a ghost update.",
    irccLastError: "Latest IRCC issue",
    irccNoHistory: "No IRCC history yet",
  },
  zh: {
    admin: "管理员",
    adminTitle: "管理后台",
    adminUsers: "用户资料",
    accountTier: "账号等级",
    accountTierStandard: "普通账号",
    accountTierPremium: "Premium 账号",
    accountTierSaved: "账号等级已保存。",
    accountTierLimits: "普通账号：1 个档案，CEAC 会自动约每小时查询一次；Issued 后降为每天一次，并在一周后自动停止。手动立即刷新限每天 1 次，并限制每日邮件数量；Premium：5 个档案，查询和邮件额度都更高。",
    accountTierCurrent: "当前账号等级",
    appSubtitle: "签证状态监控、查询历史与邮件提醒。",
    publicNoticeTitle: "服务说明 / 风险提示",
    publicNoticeBody: "CEACStatusBot 是非官方、非盈利个人项目，仅用于学习研究，以及方便站长和授权用户查询公开状态。本项目不隶属于美国国务院、CEAC、GTS、中信银行、IRCC、韩国签证门户、加拿大政府或韩国法务部。",
    publicNoticeDisclaimer: "本站不提供签证代理、官方预约、移民咨询、自动抢号、占位、结果保证或任何官方/银行/政府服务。查询结果依赖第三方网站，可能存在延迟、不可用、不完整或错误。",
    acceptTerms: "我已阅读并同意用户条款和免责声明。",
    termsTitle: "用户条款和免责声明",
    termsBody: "创建账号前请先查看完整条款。注册即表示你确认提交信息已获授权，理解本站非官方、非盈利的服务性质，并接受第三方依赖和不保证事项。",
    termsVersion: "版本",
    viewTerms: "查看并同意完整条款",
    closeTerms: "关闭条款",
    profileTermsIntro: "你可以随时在这里查看当前用户条款和免责声明。登录后打开完整条款，即记录为同意当前版本。",
    applicationId: "Application ID 或 Case Number",
    autoMonitor: "启用自动监控",
    caseCreated: "签证档案已创建。",
    caseList: "档案列表",
    caseName: "档案名称",
    caseNamePlaceholder: "例如：北京 F1 面签",
    casesOwned: "档案数量",
    changeContent: "变更内容",
    confirmDelete: "确认删除此档案？",
    createdAt: "创建时间",
    currentLogin: "当前登录",
    dashboard: "我的档案",
    deliveryEmail: "接收提醒邮箱",
    deliverySection: "邮件发送",
    emailDeliveryLogs: "发信记录",
    emailDeliveryEmptyBody: "这封较早的邮件未记录正文。",
    emailType: "邮件类型",
    recipient: "收件人",
    subject: "主题",
    body: "正文",
    duration: "耗时",
    email: "邮箱",
    emailPushOff: "邮件推送关闭",
    emailPushOn: "邮件推送开启",
    emailPushSetting: "状态更新时发送邮件推送",
    error: "失败",
    executor: "执行人",
    fastQuery: "立即查询",
    fastQueryChanged: "立即查询完成：状态已更新",
    fastQueryUnchanged: "立即查询完成：状态未变化",
    firstFiveSurname: "姓的前 5 个字母",
    firstFiveSurnameHint: "只填写姓氏前 5 个英文字母；不足 5 个按实际姓氏填写。",
    forgotPassword: "忘记密码？",
    lastCheckMode: "上次抓取方式",
    lastCheckedAt: "上次更新时间",
    lastCeacError: "最近 CEAC 查询问题",
    ceacConsecutiveErrors: "连续 CEAC 失败次数",
    lastQuery: "最近查询",
    location: "选择面签地点",
    locationMetric: "办理地点",
    keepPasswordPlaceholder: "留空则保留当前授权码",
    login: "登录",
    loginAction: "登录控制台",
    logItems: "条日志",
    logoutTitle: "退出登录",
    missingCaseNumber: "未提供流水号",
    noCases: "尚未添加档案",
    noHistory: "暂无历史状态记录",
    noLogs: "暂无日志",
    noStatus: "未就绪",
    noStatusChange: "未发生状态变更",
    notificationSent: "已发送通知",
    notificationNotSent: "未发送通知",
    moveProfileUp: "上移档案",
    moveProfileDown: "下移档案",
    profileOrderSaved: "档案顺序已保存。",
    profileOrderFailed: "档案顺序保存失败。",
    issuedSlowQueryNotice: "此档案已进入 Issued，自动查询已降频为每天一次；如果你一周内未手动停止，系统将自动停止并邮件通知你。",
    stopAutomaticQuery: "停止自动查询",
    startAutomaticQuery: "开启自动查询",
    automaticQueryStopped: "已停止自动查询，你仍然可以手动立即查询。",
    automaticQueryStarted: "已开启自动查询，系统已安排下一次自动查询。",
    notVerified: "未验证",
    newProfile: "新增",
    nextCheckAt: "下次自动查询",
    notifyEmail: "接收邮箱",
    officialIntro: "欢迎！你可以在这里查询美国签证申请状态。",
    passport: "护照号码",
    passportPlaceholder: "护照号码或 NA",
    password: "密码",
    passwordOrCode: "密码 / 授权码",
    personalInfo: "个人信息",
    profile: "案卷",
    profileSaved: "个人信息已更新。",
    refresh: "刷新数据",
    register: "注册",
    registerAction: "创建账号",
    rememberLogin: "记住账号和密码",
    rememberAccount: "记住账号",
    rememberPassword: "记住密码",
    rememberPasswordWarning: "仅建议在私人设备使用；密码会保存在当前浏览器本地。",
    resetAction: "重置密码",
    resetCodeSent: "如果该邮箱存在，重置验证码已发送。",
    resetPassword: "重置密码",
    resetPasswordSaved: "密码已重置，请重新登录。",
    resetPasswordMismatch: "两次输入的新密码不一致。",
    requestFailed: "请求失败",
    save: "保存档案",
    send: "发送",
    sendCodeFailed: "验证码发送失败",
    senderConfig: "发件人配置",
    securityEvents: "安全事件",
    securityActor: "来源",
    securityEventType: "事件",
    securitySeverity: "级别",
    signInFailed: "操作失败",
    smtpEmail: "发件邮箱",
    smtpHost: "SMTP 服务器",
    smtpPort: "SMTP 端口",
    status: "状态",
    statusHistory: "状态历史",
    statusMonitoring: "Visa Status Check",
    success: "成功",
    irccSnapshotSaved: "已获取快照",
    systemLogs: "系统监控日志",
    workerQueue: "Worker 队列",
    workerQueueEmpty: "当前没有排队或运行中的任务",
    workerScheduledQueue: "未来预计入队",
    workerScheduledQueueEmpty: "暂无未来自动查询任务",
    workerFinishedQueue: "刚刚离开队列",
    workerFinishedQueueEmpty: "暂无刚刚完成的任务",
    workerQueueCurrent: "当前队列 / 运行中",
    scheduledPosition: "预计顺序",
    expectedQueueAt: "预计入队时间",
    timeUntilQueue: "距离入队",
    finishedAt: "离开时间",
    queuePosition: "队列位置",
    queueWait: "等待时间",
    workerStatus: "任务状态",
    workerLockedBy: "Worker",
    systemEmail: "默认发信邮箱",
    systemEmailConfigured: "已配置",
    systemEmailNotConfigured: "未配置",
    systemEmailSaved: "默认发信邮箱已保存。",
    systemEmailSource: "来源",
    systemSender: "系统发信",
    testEmail: "测试发信",
    testEmailSending: "正在发送现有状态邮件。",
    testEmailSent: "测试邮件已按当前状态模板发送。",
    themeToDark: "切换至暗色模式",
    themeToLight: "切换至亮色模式",
    updatePushDisabled: "已关闭状态更新邮件推送。",
    updatePushEnabled: "已开启状态更新邮件推送。",
    updatedAt: "更新时间",
    useCustomSmtp: "自定义 SMTP",
    useSsl: "启用 SSL",
    triggerAutomatic: "自动抓取",
    triggerManual: "手动抓取",
    triggerUnknown: "未知",
    verificationCode: "验证码",
    verificationCodeSent: "验证码已发送，请查看邮箱。",
    verified: "已验证",
    visaApplicationType: "Visa Application Type",
    visaTypeNiv: "非移民签证（NIV）",
    waitFirstQuery: "等待首次查询",
    queryHint: "请选择面签地点，并输入你的 Application ID 或 Case Number。",
    queryQueued: "当前有其他查询正在处理，你的查询已加入队列。前方任务很快会处理完毕，轮到你后会自动开始查询，请不要重复点击。",
    queryInProgress: "正在查询 CEAC，请稍候。",
    pre2022Note: "注意：如果你在 2022 年 1 月 1 日之前完成表格，请在护照号码和姓氏字段填写 NA。",
    passportSlotMonitor: "护照预约监控",
    passportSlotIntro: "Approved 或 Issued 后填写 UID/HAL，系统会轮询 GTS 可预约时间。",
    passportSlotEarlyHint: "你可以提前配置；但 GTS 通常在 Approved 或 Issued 后才会返回有效 token。",
    passportSlotDetectionOnly: "本功能只负责检测 GTS 官网返回的可预约 slot 并发送提醒，不支持自动预约、占位或抢 slot，也不保证结果完整、实时一致或一定预约成功。",
    passportSlotIdentifier: "UID 或 HAL",
    passportSlotIdentifierPlaceholder: "106417002 或 HAL0123456789",
    passportSlotSave: "保存监控",
    passportSlotSaved: "护照预约监控已保存。",
    passportSlotEnabled: "已开启 GTS 监控。",
    passportSlotDisabled: "已关闭 GTS 监控。",
    passportSlotEmailEnabled: "已开启 GTS slot 邮件推送。",
    passportSlotEmailDisabled: "已关闭 GTS slot 邮件推送。",
    passportSlotBookedStop: "我已预约，停止监控",
    passportSlotBookedStopped: "已停止护照预约监控，邮件开关和历史记录已保留。",
    passportSlotManualQuery: "立即查询 slot",
    passportSlotTestEmail: "测试 GTS 邮件",
    passportSlotTestEmailSending: "正在发送 GTS 监控测试邮件。",
    passportSlotTestEmailSent: "GTS 监控测试邮件已发送。",
    passportSlotQueued: "当前有其他查询正在处理，你的 GTS slot 查询已加入队列。前方任务很快会处理完毕，轮到你后会自动开始查询，请不要重复点击。",
    passportSlotQuerying: "正在查询 GTS slot，请稍候。",
    passportSlotFound: "GTS slot 查询完成：发现可预约时间。",
    passportSlotNotFound: "GTS slot 查询完成：暂无可预约时间。",
    passportSlotChanged: "GTS slot 结果发生变化。",
    passportSlotConfigured: "已配置编号",
    passportSlotCurrentStatus: "当前 GTS 状态",
    passportSlotNotEligible: "暂不具备护照预约资格。",
    passportSlotNoSlot: "已可预约但暂无 slot。",
    passportSlotStatusHasSlot: "发现可预约时间。",
    passportSlotLastCount: "最近 slot 数量",
    passportSlotLastError: "最近 GTS 错误",
    passportSlotHistory: "slot 变化历史",
    ceacAutoLockedByPassportSlot: "GTS 已确认护照进入可预约阶段，系统已自动停止该档案的 CEAC 自动查询；只有管理员可以恢复。",
    restoreCeacAutoQuery: "恢复 CEAC 自动查询",
    ceacAutoQueryRestored: "已恢复 CEAC 自动查询。",
    supportTitle: "支持这个非盈利项目",
    supportBody: "如果 CEACStatusBot 对你有帮助，欢迎自愿赞赏支持服务器和维护成本。",
    supportPremium: "Premium 升级方式：在小红书发布包含网站链接、使用截图和使用感受的帖子后联系管理员；或赞赏时备注账号邮箱，管理员人工核对后升级。",
    supportDisclaimer: "本站为非官方服务，不隶属于美国国务院、CEAC、GTS、中信银行、IRCC、韩国签证门户、加拿大政府或韩国法务部。赞赏是自愿支持，不购买官方服务，不保证签证结果、护照进度、slot 可用性、IRCC 更新或预约成功。请勿公开截图泄露 UID/HAL/护照/IRCC/韩国签证等个人信息。",
    nonprofitNotice: "非盈利个人项目",
    contactEmail: "联系邮箱：ceac-admin@mikezhuang.cn",
    sourceCode: "开源仓库",
    workerPriority: "Worker 优先级",
    workerPriorityHint: "数值越小越优先。Premium 默认 50，普通账号默认 100。",
    saveWorkerPriority: "保存优先级",
    workerPrioritySaved: "Worker 优先级已保存。",
    noPassportSlotMonitor: "尚未配置 UID/HAL 监控",
    noPassportSlotHistory: "暂无 slot 变化记录",
    country: "国家",
    countryUnitedStates: "美国",
    countryCanada: "加拿大",
    countryKorea: "韩国",
    koreaVisaTitle: "韩国签证查询",
    koreaQueryHint: "当前支持“驻外使领馆 + 护照号码”查询。英文姓名请按护照填写。",
    koreaEnglishName: "英文姓名",
    koreaNameHint: "先姓后名，拼音大写，姓名中间留空格。",
    koreaBirthDate: "出生日期",
    koreaApplicationNo: "申请编号",
    koreaApplicationDate: "申请日期",
    koreaEntryPurpose: "入境目的",
    koreaProgressStatus: "进行状态",
    koreaSave: "保存韩国签证档案",
    koreaQuerying: "正在查询韩国签证门户，请稍候。",
    koreaQueued: "韩国签证查询已加入队列。",
    koreaChanged: "韩国签证查询完成：状态已变化。",
    koreaUnchanged: "韩国签证查询完成：状态未变化。",
    koreaTestEmail: "测试韩国签证邮件",
    koreaTestEmailSending: "正在发送韩国签证测试邮件。",
    koreaTestEmailSent: "韩国签证测试邮件已发送。",
    koreaLastError: "最近韩国签证问题",
    koreaNoHistory: "暂无韩国签证历史记录",
    irccAlphaLabel: "Alpha",
    irccPortalTitle: "IRCC Portal 监控",
    irccPortalIntro: "Alpha：当前仅支持 IRCC Portal。请谨慎使用，未经充分测试；未来计划支持 IRCC Portal – New version 和 GCKey。",
    irccPortalEmail: "IRCC Portal 邮箱",
    irccPortalPassword: "IRCC Portal 密码",
    irccDiscoverApplications: "发现已提交申请",
    irccApplicationFound: "已发现申请。请选择一项，或手动填写 appId。",
    irccApplicationSelect: "已提交申请",
    irccAppId: "IRCC appId",
    irccApplicationNumber: "Application number",
    irccPrincipalApplicant: "主申请人",
    irccSave: "保存 IRCC 档案",
    irccQuerying: "正在查询 IRCC Portal，请稍候。",
    irccQueued: "IRCC 查询已加入队列。",
    irccChanged: "IRCC 查询完成：快照已变化。",
    irccUnchanged: "IRCC 查询完成：快照未变化。",
    irccTestEmail: "测试 IRCC 邮件",
    irccTestEmailSending: "正在发送 IRCC 测试邮件。",
    irccTestEmailSent: "IRCC 测试邮件已发送。",
    irccApplicationStatus: "申请状态",
    irccStatusOverview: "当前概括状态",
    irccOverallStatus: "总体状态",
    irccLatestUpdate: "Latest update",
    irccApplicantInfo: "申请人信息",
    irccMessages: "申请消息",
    irccGhostUpdate: "首页更新时间来自 submitted applications 页面；它变化但详情页可见状态不变时，会记录为 ghost update。",
    irccLastError: "最近 IRCC 问题",
    irccNoHistory: "暂无 IRCC 历史记录",
  },
} as const;

type TranslationKey = keyof typeof translations.en;

async function requestJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent("ceac-session-expired", { detail: payload.detail ?? "Session expired" }));
    }
    throw new Error(payload.detail ?? "Request failed");
  }
  return payload as T;
}

function getBrowserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}

async function waitForQueryJob(
  jobId: number,
  onStatusChange?: (status: QueryJob["status"]) => void,
): Promise<QueryJob | null> {
  let job: QueryJob | null = null;
  const queueWaitStartedAt = Date.now();
  let lastStatus: QueryJob["status"] | null = null;
  while (true) {
    const jobPayload = await requestJson<{ job: QueryJob }>(`/api/query-jobs/${jobId}`);
    job = jobPayload.job;
    if (job.status !== lastStatus) {
      lastStatus = job.status;
      onStatusChange?.(job.status);
    }
    if (job.status === "succeeded" || job.status === "failed") {
      break;
    }
    if (job.status === "queued" && Date.now() - queueWaitStartedAt >= QUERY_JOB_QUEUE_WAIT_MS) {
      break;
    }
    await new Promise((resolve) => window.setTimeout(resolve, QUERY_JOB_POLL_INTERVAL_MS));
  }
  return job;
}

async function waitForIrccQueryJob(
  jobId: number,
  onStatusChange?: (status: IrccQueryJob["status"]) => void,
): Promise<IrccQueryJob | null> {
  let job: IrccQueryJob | null = null;
  const queueWaitStartedAt = Date.now();
  let lastStatus: IrccQueryJob["status"] | null = null;
  while (true) {
    const jobPayload = await requestJson<{ job: IrccQueryJob }>(`/api/ircc/query-jobs/${jobId}`);
    job = jobPayload.job;
    if (job.status !== lastStatus) {
      lastStatus = job.status;
      onStatusChange?.(job.status);
    }
    if (job.status === "succeeded" || job.status === "failed") {
      break;
    }
    if (job.status === "queued" && Date.now() - queueWaitStartedAt >= QUERY_JOB_QUEUE_WAIT_MS) {
      break;
    }
    await new Promise((resolve) => window.setTimeout(resolve, QUERY_JOB_POLL_INTERVAL_MS));
  }
  return job;
}

async function waitForKoreaQueryJob(
  jobId: number,
  onStatusChange?: (status: KoreaQueryJob["status"]) => void,
): Promise<KoreaQueryJob | null> {
  let job: KoreaQueryJob | null = null;
  const queueWaitStartedAt = Date.now();
  let lastStatus: KoreaQueryJob["status"] | null = null;
  while (true) {
    const jobPayload = await requestJson<{ job: KoreaQueryJob }>(`/api/korea/query-jobs/${jobId}`);
    job = jobPayload.job;
    if (job.status !== lastStatus) {
      lastStatus = job.status;
      onStatusChange?.(job.status);
    }
    if (job.status === "succeeded" || job.status === "failed") {
      break;
    }
    if (job.status === "queued" && Date.now() - queueWaitStartedAt >= QUERY_JOB_QUEUE_WAIT_MS) {
      break;
    }
    await new Promise((resolve) => window.setTimeout(resolve, QUERY_JOB_POLL_INTERVAL_MS));
  }
  return job;
}

function getInitialTheme(): ThemeMode {
  const stored = localStorage.getItem("themeMode");
  if (stored === "dark" || stored === "light") {
    return stored;
  }
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function getInitialLanguage(): LanguageMode {
  const stored = localStorage.getItem("languageMode");
  if (stored === "zh" || stored === "en") {
    return stored;
  }
  return navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
}

function parsePortableTime(value: string | number): Date | null {
  if (typeof value === "number") {
    const timestamp = value < 1_000_000_000_000 ? value * 1000 : value;
    const parsed = new Date(timestamp);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  if (/^\d+$/.test(trimmed)) {
    return parsePortableTime(Number(trimmed));
  }
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(trimmed);
  const normalized = hasTimezone ? trimmed : trimmed.replace(" ", "T") + "Z";
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatTime(value: string | number | null, languageMode: LanguageMode): string {
  if (!value) {
    return languageMode === "zh" ? "尚未记录" : "Not recorded";
  }
  const parsed = parsePortableTime(value);
  if (!parsed) {
    return String(value);
  }
  return parsed.toLocaleString(languageMode === "zh" ? "zh-CN" : "en-US");
}

function formatInlineTimes(value: string, languageMode: LanguageMode): string {
  return value.replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})/g, (matched) => {
    const formatted = formatTime(matched, languageMode);
    return formatted === matched ? matched : formatted;
  });
}

function formatDurationSeconds(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes > 0 ? `${minutes}m ${rest}s` : `${rest}s`;
}

function formatTriggerType(value: CeacCase["lastTriggerType"] | QueryTriggerType | IrccCase["lastTriggerType"] | KoreaCase["lastTriggerType"], t: (key: TranslationKey) => string): string {
  if (value === "ircc_manual") {
    return `${t("irccPortalTitle")} · ${t("triggerManual")}`;
  }
  if (value === "ircc_automatic") {
    return `${t("irccPortalTitle")} · ${t("triggerAutomatic")}`;
  }
  if (value === "korea_manual") {
    return `${t("koreaVisaTitle")} · ${t("triggerManual")}`;
  }
  if (value === "korea_automatic") {
    return `${t("koreaVisaTitle")} · ${t("triggerAutomatic")}`;
  }
  if (value === "passport_slot_manual") {
    return `${t("passportSlotMonitor")} · ${t("triggerManual")}`;
  }
  if (value === "passport_slot_automatic") {
    return `${t("passportSlotMonitor")} · ${t("triggerAutomatic")}`;
  }
  if (value === "manual") {
    return `CEAC 美签状态 · ${t("triggerManual")}`;
  }
  if (value === "automatic") {
    return `CEAC 美签状态 · ${t("triggerAutomatic")}`;
  }
  return t("triggerUnknown");
}

function formatAccountTier(value: AccountTier, t: (key: TranslationKey) => string): string {
  return value === "premium" ? t("accountTierPremium") : t("accountTierStandard");
}

function getStatusTone(status: string | null | undefined): "issued" | "approved" | "refused" | "idle" | "" {
  const normalized = (status ?? "").trim().toLowerCase();
  if (normalized === "issued") {
    return "issued";
  }
  if (normalized === "approved") {
    return "approved";
  }
  if (normalized === "refused") {
    return "refused";
  }
  if (normalized.includes("暂无查询资料") || normalized.includes("no data")) {
    return "idle";
  }
  return "";
}

function getStatusBadgeClass(status: string | null | undefined, extraClass = ""): string {
  const tone = getStatusTone(status);
  return ["status-badge", tone ? `status-${tone}` : "", extraClass].filter(Boolean).join(" ");
}

function isIssuedStatus(status: string | null | undefined): boolean {
  return getStatusTone(status) === "issued";
}

function isPassportSlotReadyStatus(status: string | null | undefined): boolean {
  const tone = getStatusTone(status);
  return tone === "approved" || tone === "issued";
}

function getRememberedCredentials(): { email: string; password: string; rememberAccount: boolean; rememberPassword: boolean } {
  const rememberPassword = localStorage.getItem("rememberLogin") === "true" || localStorage.getItem("rememberPassword") === "true";
  const rememberAccount = rememberPassword || localStorage.getItem("rememberAccount") !== "false";
  return {
    email: rememberAccount ? localStorage.getItem("rememberedEmail") ?? "" : "",
    password: rememberPassword ? localStorage.getItem("rememberedPassword") ?? "" : "",
    rememberAccount,
    rememberPassword,
  };
}

export function App() {
  const [themeMode, setThemeMode] = useState<ThemeMode>(getInitialTheme);
  const [languageMode, setLanguageMode] = useState<LanguageMode>(getInitialLanguage);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [viewMode, setViewMode] = useState<ViewMode>("dashboard");
  const [user, setUser] = useState<User | null>(null);
  const [cases, setCases] = useState<CeacCase[]>([]);
  const [irccCases, setIrccCases] = useState<IrccCase[]>([]);
  const [koreaCases, setKoreaCases] = useState<KoreaCase[]>([]);
  const [adminCases, setAdminCases] = useState<AdminCase[]>([]);
  const [adminUsers, setAdminUsers] = useState<AdminUser[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [irccHistory, setIrccHistory] = useState<IrccHistoryItem[]>([]);
  const [koreaHistory, setKoreaHistory] = useState<KoreaHistoryItem[]>([]);
  const [passportSlotMonitor, setPassportSlotMonitor] = useState<PassportSlotMonitor | null>(null);
  const [passportSlotHistory, setPassportSlotHistory] = useState<PassportSlotHistoryItem[]>([]);
  const [passportSlotIdentifier, setPassportSlotIdentifier] = useState("");
  const [queryRuns, setQueryRuns] = useState<QueryRun[]>([]);
  const [queryJobs, setQueryJobs] = useState<AdminQueryJob[]>([]);
  const [scheduledQueryJobs, setScheduledQueryJobs] = useState<AdminScheduledQueryJob[]>([]);
  const [finishedQueryJobs, setFinishedQueryJobs] = useState<AdminFinishedQueryJob[]>([]);
  const [securityEvents, setSecurityEvents] = useState<SecurityEvent[]>([]);
  const [emailDeliveryLogs, setEmailDeliveryLogs] = useState<EmailDeliveryLog[]>([]);
  const [systemEmailConfig, setSystemEmailConfig] = useState<SystemEmailConfig | null>(null);
  const [systemEmailForm, setSystemEmailForm] = useState<SystemEmailForm>({
    fromEmail: "",
    host: "smtp.exmail.qq.com",
    port: "465",
    useSsl: true,
    password: "",
  });
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [selectedIrccCaseId, setSelectedIrccCaseId] = useState<number | null>(null);
  const [selectedKoreaCaseId, setSelectedKoreaCaseId] = useState<number | null>(null);
  const [newProfileCountry, setNewProfileCountry] = useState<ProfileCountry>("us");
  const [isCreatingProfile, setIsCreatingProfile] = useState(false);
  const [casesLoaded, setCasesLoaded] = useState(false);
  const [irccCasesLoaded, setIrccCasesLoaded] = useState(false);
  const [koreaCasesLoaded, setKoreaCasesLoaded] = useState(false);
  const [caseForm, setCaseForm] = useState<CaseForm>(emptyCaseForm);
  const [irccCaseForm, setIrccCaseForm] = useState<IrccCaseForm>(emptyIrccCaseForm);
  const [koreaCaseForm, setKoreaCaseForm] = useState<KoreaCaseForm>(emptyKoreaCaseForm);
  const [irccApplications, setIrccApplications] = useState<IrccDiscoveredApplication[]>([]);
  const [profileForm, setProfileForm] = useState<ProfileForm>({
    email: "",
    currentPassword: "",
    newPassword: "",
    confirmPassword: "",
  });
  const rememberedCredentials = useMemo(getRememberedCredentials, []);
  const [authEmail, setAuthEmail] = useState(rememberedCredentials.email);
  const [authPassword, setAuthPassword] = useState(rememberedCredentials.password);
  const [rememberAccount, setRememberAccount] = useState(rememberedCredentials.rememberAccount);
  const [rememberPassword, setRememberPassword] = useState(rememberedCredentials.rememberPassword);
  const [registerCode, setRegisterCode] = useState("");
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [isTermsDialogOpen, setIsTermsDialogOpen] = useState(false);
  const [resetCode, setResetCode] = useState("");
  const [resetConfirmPassword, setResetConfirmPassword] = useState("");
  const [message, setMessage] = useState<{ scope: MessageScope; text: string } | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const t = (key: TranslationKey) => translations[languageMode][key];
  const activeScope: MessageScope = user ? viewMode : "auth";
  const activeMessage = message?.scope === activeScope ? message.text : "";

  function showMessage(text: string, scope: MessageScope = activeScope) {
    setMessage(text ? { scope, text } : null);
  }

  async function syncBrowserTimezone(nextUser: User) {
    const timezone = getBrowserTimezone();
    if (!timezone || nextUser.timezone === timezone) {
      return;
    }
    try {
      const payload = await requestJson<{ user: User }>("/api/me/timezone", {
        method: "PATCH",
        body: JSON.stringify({ timezone }),
      });
      setUser(payload.user);
    } catch {
      // 时区只影响邮件展示，不应阻塞登录和主流程。
    }
  }

  useEffect(() => {
    document.documentElement.dataset.theme = themeMode;
    localStorage.setItem("themeMode", themeMode);
  }, [themeMode]);

  useEffect(() => {
    document.documentElement.lang = languageMode === "zh" ? "zh-CN" : "en";
    localStorage.setItem("languageMode", languageMode);
  }, [languageMode]);

  useEffect(() => {
    requestJson<{ user: User }>("/api/me")
      .then((payload) => {
        setUser(payload.user);
        void syncBrowserTimezone(payload.user);
        setProfileForm((current) => ({ ...current, email: payload.user.email }));
        setCaseForm((current) => current.receiveEmail ? current : createEmptyCaseForm(payload.user.email));
        setIrccCaseForm((current) => current.receiveEmail ? current : createEmptyIrccCaseForm(payload.user.email));
        setKoreaCaseForm((current) => current.receiveEmail ? current : createEmptyKoreaCaseForm(payload.user.email));
        void loadCases();
        void loadIrccCases();
        void loadKoreaCases();
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const handleSessionExpired = (event: Event) => {
      const detail = event instanceof CustomEvent ? String(event.detail || "") : "";
      setUser(null);
      setCases([]);
      setIrccCases([]);
      setKoreaCases([]);
      setCasesLoaded(false);
      setIrccCasesLoaded(false);
      setKoreaCasesLoaded(false);
      setIsCreatingProfile(false);
      setHistory([]);
      setIrccHistory([]);
      setKoreaHistory([]);
      showMessage(detail || (languageMode === "zh" ? "登录已超时，请重新登录。" : "Session expired. Please sign in again."), "auth");
    };
    window.addEventListener("ceac-session-expired", handleSessionExpired);
    return () => window.removeEventListener("ceac-session-expired", handleSessionExpired);
  }, [languageMode]);

  const orderedProfiles = useMemo<ProfileListItem[]>(() => {
    return [
      ...cases.map((item) => ({
        profileType: "ceac" as const,
        id: item.id,
        sortOrder: item.sortOrder ?? 0,
        updatedAt: item.updatedAt,
        case: item,
      })),
      ...irccCases.map((item) => ({
        profileType: "ircc" as const,
        id: item.id,
        sortOrder: item.sortOrder ?? 0,
        updatedAt: item.updatedAt,
        case: item,
      })),
      ...koreaCases.map((item) => ({
        profileType: "korea" as const,
        id: item.id,
        sortOrder: item.sortOrder ?? 0,
        updatedAt: item.updatedAt,
        case: item,
      })),
    ].sort((left, right) => {
      if (left.sortOrder !== right.sortOrder) {
        return left.sortOrder - right.sortOrder;
      }
      return new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime();
    });
  }, [cases, irccCases, koreaCases]);

  useEffect(() => {
    if (!casesLoaded || !irccCasesLoaded || !koreaCasesLoaded || isCreatingProfile) {
      return;
    }
    const currentSelectionExists = selectedKoreaCaseId !== null
      ? koreaCases.some((item) => item.id === selectedKoreaCaseId)
      : selectedIrccCaseId !== null
        ? irccCases.some((item) => item.id === selectedIrccCaseId)
        : selectedCaseId !== null && cases.some((item) => item.id === selectedCaseId);
    if (currentSelectionExists) {
      return;
    }
    const firstProfile = orderedProfiles[0];
    if (!firstProfile) {
      setSelectedCaseId(null);
      setSelectedIrccCaseId(null);
      setSelectedKoreaCaseId(null);
      return;
    }
    if (firstProfile.profileType === "ceac") {
      setSelectedCaseId(firstProfile.id);
      setSelectedIrccCaseId(null);
      setSelectedKoreaCaseId(null);
    } else if (firstProfile.profileType === "ircc") {
      setSelectedCaseId(null);
      setSelectedIrccCaseId(firstProfile.id);
      setSelectedKoreaCaseId(null);
    } else {
      setSelectedCaseId(null);
      setSelectedIrccCaseId(null);
      setSelectedKoreaCaseId(firstProfile.id);
    }
  }, [cases, casesLoaded, irccCases, irccCasesLoaded, koreaCases, koreaCasesLoaded, isCreatingProfile, orderedProfiles, selectedCaseId, selectedIrccCaseId, selectedKoreaCaseId]);

  const selectedCase = useMemo(
    () => selectedIrccCaseId === null && selectedKoreaCaseId === null && selectedCaseId !== null ? cases.find((item) => item.id === selectedCaseId) ?? null : null,
    [cases, selectedCaseId, selectedIrccCaseId, selectedKoreaCaseId],
  );
  const selectedIrccCase = useMemo(
    () => selectedIrccCaseId === null || selectedKoreaCaseId !== null ? null : irccCases.find((item) => item.id === selectedIrccCaseId) ?? null,
    [irccCases, selectedIrccCaseId, selectedKoreaCaseId],
  );
  const selectedKoreaCase = useMemo(
    () => selectedKoreaCaseId === null ? null : koreaCases.find((item) => item.id === selectedKoreaCaseId) ?? null,
    [koreaCases, selectedKoreaCaseId],
  );

  useEffect(() => {
    if (selectedCase) {
      void loadHistory(selectedCase.id);
      void loadPassportSlotMonitor(selectedCase.id);
    } else {
      setHistory([]);
      setPassportSlotMonitor(null);
      setPassportSlotHistory([]);
      setPassportSlotIdentifier("");
    }
  }, [selectedCase?.id]);

  useEffect(() => {
    if (selectedIrccCase) {
      void loadIrccHistory(selectedIrccCase.id);
    } else {
      setIrccHistory([]);
    }
  }, [selectedIrccCase?.id]);

  useEffect(() => {
    if (selectedKoreaCase) {
      void loadKoreaHistory(selectedKoreaCase.id);
    } else {
      setKoreaHistory([]);
    }
  }, [selectedKoreaCase?.id]);

  async function loadCases() {
    const payload = await requestJson<{ cases: CeacCase[] }>("/api/cases");
    setCases(payload.cases);
    setCasesLoaded(true);
  }

  async function loadIrccCases() {
    const payload = await requestJson<{ cases: IrccCase[] }>("/api/ircc/cases");
    setIrccCases(payload.cases);
    setIrccCasesLoaded(true);
  }

  async function loadKoreaCases() {
    const payload = await requestJson<{ cases: KoreaCase[] }>("/api/korea/cases");
    setKoreaCases(payload.cases);
    setKoreaCasesLoaded(true);
  }

  async function loadHistory(caseId: number) {
    const payload = await requestJson<{ history: HistoryItem[] }>(`/api/cases/${caseId}/history`);
    setHistory(payload.history);
  }

  async function loadIrccHistory(caseId: number) {
    const payload = await requestJson<{ history: IrccHistoryItem[] }>(`/api/ircc/cases/${caseId}/history`);
    setIrccHistory(payload.history);
  }

  async function loadKoreaHistory(caseId: number) {
    const payload = await requestJson<{ history: KoreaHistoryItem[] }>(`/api/korea/cases/${caseId}/history`);
    setKoreaHistory(payload.history);
  }

  async function loadPassportSlotMonitor(caseId: number) {
    const payload = await requestJson<{ monitor: PassportSlotMonitor | null; history: PassportSlotHistoryItem[] }>(
      `/api/cases/${caseId}/passport-slot-monitor`,
    );
    setPassportSlotMonitor(payload.monitor);
    setPassportSlotHistory(payload.history);
    setPassportSlotIdentifier(payload.monitor?.identifier ?? "");
  }

  async function loadAdminData() {
    const [runsPayload, jobsPayload, casesPayload, usersPayload, systemEmailPayload, securityEventsPayload, emailDeliveryPayload] = await Promise.all([
      requestJson<{ runs: QueryRun[] }>("/api/admin/query-runs"),
      requestJson<{ jobs: AdminQueryJob[]; scheduledJobs: AdminScheduledQueryJob[]; finishedJobs: AdminFinishedQueryJob[] }>("/api/admin/query-jobs"),
      requestJson<{ cases: AdminCase[] }>("/api/admin/cases"),
      requestJson<{ users: AdminUser[] }>("/api/admin/users"),
      requestJson<{ config: SystemEmailConfig }>("/api/admin/system-email"),
      requestJson<{ events: SecurityEvent[] }>("/api/admin/security-events?limit=200"),
      requestJson<{ deliveries: EmailDeliveryLog[] }>("/api/admin/email-deliveries?limit=200"),
    ]);
    setQueryRuns(runsPayload.runs);
    setQueryJobs(jobsPayload.jobs);
    setScheduledQueryJobs(jobsPayload.scheduledJobs);
    setFinishedQueryJobs(jobsPayload.finishedJobs);
    setAdminCases(casesPayload.cases);
    setAdminUsers(usersPayload.users);
    setSecurityEvents(securityEventsPayload.events);
    setEmailDeliveryLogs(emailDeliveryPayload.deliveries);
    setSystemEmailConfig(systemEmailPayload.config);
    setSystemEmailForm({
      fromEmail: systemEmailPayload.config.fromEmail,
      host: systemEmailPayload.config.host,
      port: String(systemEmailPayload.config.port),
      useSsl: systemEmailPayload.config.useSsl,
      password: "",
    });
  }

  async function loadAdminQueueData() {
    const jobsPayload = await requestJson<{ jobs: AdminQueryJob[]; scheduledJobs: AdminScheduledQueryJob[]; finishedJobs: AdminFinishedQueryJob[] }>("/api/admin/query-jobs");
    setQueryJobs(jobsPayload.jobs);
    setScheduledQueryJobs(jobsPayload.scheduledJobs);
    setFinishedQueryJobs(jobsPayload.finishedJobs);
  }

  useEffect(() => {
    if (user?.role !== "admin" || viewMode !== "admin") {
      return undefined;
    }
    let isCancelled = false;
    const refreshQueue = async () => {
      try {
        const jobsPayload = await requestJson<{ jobs: AdminQueryJob[]; scheduledJobs: AdminScheduledQueryJob[]; finishedJobs: AdminFinishedQueryJob[] }>("/api/admin/query-jobs");
        if (!isCancelled) {
          setQueryJobs(jobsPayload.jobs);
          setScheduledQueryJobs(jobsPayload.scheduledJobs);
          setFinishedQueryJobs(jobsPayload.finishedJobs);
        }
      } catch {
        // 轻量自动刷新失败时保持当前画面，下一轮继续尝试。
      }
    };
    void refreshQueue();
    const timer = window.setInterval(refreshQueue, ADMIN_QUEUE_REFRESH_INTERVAL_MS);
    return () => {
      isCancelled = true;
      window.clearInterval(timer);
    };
  }, [user?.role, viewMode]);

  async function saveSystemEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsBusy(true);
    showMessage("");
    try {
      const payload = await requestJson<{ config: SystemEmailConfig }>("/api/admin/system-email", {
        method: "PUT",
        body: JSON.stringify({
          fromEmail: systemEmailForm.fromEmail,
          host: systemEmailForm.host,
          port: Number(systemEmailForm.port),
          useSsl: systemEmailForm.useSsl,
          password: systemEmailForm.password || null,
        }),
      });
      setSystemEmailConfig(payload.config);
      setSystemEmailForm((current) => ({ ...current, password: "" }));
      showMessage(t("systemEmailSaved"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsBusy(true);
    showMessage("");
    try {
      if (authMode === "forgot") {
        if (authPassword !== resetConfirmPassword) {
          showMessage(t("resetPasswordMismatch"));
          return;
        }
        await requestJson<{ ok: boolean }>("/api/auth/reset-password", {
          method: "POST",
          body: JSON.stringify({ email: authEmail, code: resetCode, password: authPassword }),
        });
        setAuthMode("login");
        setAuthPassword("");
        setResetCode("");
        setResetConfirmPassword("");
        showMessage(t("resetPasswordSaved"));
        return;
      }
      const path = authMode === "login" ? "/api/auth/login" : "/api/auth/register";
      const body = authMode === "login"
        ? { email: authEmail, password: authPassword }
        : { email: authEmail, password: authPassword, code: registerCode, acceptedTerms };
      const payload = await requestJson<{ user: User }>(path, {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (authMode === "login" && rememberAccount) {
        localStorage.setItem("rememberAccount", "true");
        localStorage.setItem("rememberedEmail", authEmail);
      } else if (authMode === "login") {
        localStorage.setItem("rememberAccount", "false");
        localStorage.removeItem("rememberedEmail");
      }
      if (authMode === "login" && rememberPassword) {
        localStorage.setItem("rememberPassword", "true");
        localStorage.removeItem("rememberLogin");
        localStorage.setItem("rememberedPassword", authPassword);
      } else if (authMode === "login") {
        localStorage.removeItem("rememberLogin");
        localStorage.removeItem("rememberPassword");
        localStorage.removeItem("rememberedPassword");
      }
      setUser(payload.user);
      void syncBrowserTimezone(payload.user);
      setAcceptedTerms(false);
      setProfileForm({ email: payload.user.email, currentPassword: "", newPassword: "", confirmPassword: "" });
      setCaseForm((current) => current.receiveEmail ? current : createEmptyCaseForm(payload.user.email));
      setIrccCaseForm((current) => current.receiveEmail ? current : createEmptyIrccCaseForm(payload.user.email));
      setKoreaCaseForm((current) => current.receiveEmail ? current : createEmptyKoreaCaseForm(payload.user.email));
      setIsCreatingProfile(false);
      setCasesLoaded(false);
      setIrccCasesLoaded(false);
      setKoreaCasesLoaded(false);
      await Promise.all([loadCases(), loadIrccCases(), loadKoreaCases()]);
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("signInFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function sendCode() {
    setIsBusy(true);
    showMessage("");
    try {
      const path = authMode === "forgot" ? "/api/auth/send-password-reset-code" : "/api/auth/send-code";
      await requestJson<{ ok: boolean }>(path, {
        method: "POST",
        body: JSON.stringify({ email: authEmail }),
      });
      showMessage(authMode === "forgot" ? t("resetCodeSent") : t("verificationCodeSent"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("sendCodeFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function logout() {
    await requestJson<{ ok: boolean }>("/api/auth/logout", { method: "POST", body: "{}" });
    setUser(null);
    setCases([]);
    setIrccCases([]);
    setKoreaCases([]);
    setCasesLoaded(false);
    setIrccCasesLoaded(false);
    setKoreaCasesLoaded(false);
    setIsCreatingProfile(false);
    setHistory([]);
    setIrccHistory([]);
    setKoreaHistory([]);
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsBusy(true);
    showMessage("");
    if (profileForm.newPassword && profileForm.newPassword !== profileForm.confirmPassword) {
      showMessage(languageMode === "zh" ? "两次输入的新密码不一致。" : "New passwords do not match.");
      setIsBusy(false);
      return;
    }
    try {
      const payload = await requestJson<{ user: User }>("/api/me", {
        method: "PATCH",
        body: JSON.stringify({
          email: profileForm.email,
          currentPassword: profileForm.currentPassword,
          newPassword: profileForm.newPassword || null,
        }),
      });
      setUser(payload.user);
      void syncBrowserTimezone(payload.user);
      setProfileForm({ email: payload.user.email, currentPassword: "", newPassword: "", confirmPassword: "" });
      localStorage.setItem("rememberedEmail", payload.user.email);
      showMessage(t("profileSaved"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function acceptCurrentTerms() {
    await requestJson<{ ok: boolean; termsVersion: string; acceptedAt: string }>("/api/me/terms-acceptance", {
      method: "POST",
    });
  }

  async function saveCase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsBusy(true);
    showMessage("");
    try {
      const payload = {
        displayName: caseForm.displayName,
        location: caseForm.location,
        applicationNum: caseForm.applicationNum,
        passportNumber: caseForm.passportNumber,
        surname: caseForm.surname,
        receiveEmail: caseForm.receiveEmail || null,
        senderMode: caseForm.senderMode,
        isEnabled: caseForm.isEnabled,
        emailNotificationsEnabled: caseForm.emailNotificationsEnabled,
        smtpConfig: caseForm.senderMode === "custom"
          ? {
              fromEmail: caseForm.smtpFromEmail,
              host: caseForm.smtpHost,
              port: Number(caseForm.smtpPort),
              useSsl: caseForm.smtpUseSsl,
              password: caseForm.smtpPassword,
            }
          : null,
      };
      const result = await requestJson<{
        case: CeacCase;
        initialQueryJob?: { jobId: number; status: QueryJob["status"] } | null;
      }>("/api/cases", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setCaseForm(createEmptyCaseForm(user?.email ?? ""));
      setSelectedCaseId(result.case.id);
      setSelectedIrccCaseId(null);
      setSelectedKoreaCaseId(null);
      setIsCreatingProfile(false);
      await loadCases();
      if (result.initialQueryJob) {
        const job = await waitForQueryJob(result.initialQueryJob.jobId, (status) => {
          if (status === "queued") {
            showMessage(t("queryQueued"));
          } else if (status === "running") {
            showMessage(t("queryInProgress"));
          }
        });
        await loadCases();
        await loadHistory(result.case.id);
        if (!job || (job.status !== "succeeded" && job.status !== "failed")) {
          showMessage(job?.status === "queued" ? t("queryQueued") : t("queryInProgress"));
          return;
        }
        const queryResult = job.result;
        showMessage(
          queryResult?.success
            ? (queryResult.changed ? t("fastQueryChanged") : t("fastQueryUnchanged"))
            : (job.errorMessage || queryResult?.error || t("requestFailed")),
        );
        return;
      }
      showMessage(t("caseCreated"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function discoverIrccApplications(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    setIsBusy(true);
    showMessage("");
    try {
      const payload = await requestJson<{ applications: IrccDiscoveredApplication[] }>("/api/ircc/applications/discover", {
        method: "POST",
        body: JSON.stringify({
          portalEmail: irccCaseForm.portalEmail,
          portalPassword: irccCaseForm.portalPassword,
        }),
      });
      setIrccApplications(payload.applications);
      const first = payload.applications[0];
      if (first) {
        setIrccCaseForm((current) => ({
          ...current,
          appId: first.appId,
          applicationNumber: first.applicationNumber,
          principalApplicant: first.principalApplicant,
          displayName: current.displayName || `IRCC ${first.applicationNumber || first.appId}`,
        }));
      }
      showMessage(t("irccApplicationFound"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function saveIrccCase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsBusy(true);
    showMessage("");
    try {
      const payload = {
        displayName: irccCaseForm.displayName,
        portalEmail: irccCaseForm.portalEmail,
        portalPassword: irccCaseForm.portalPassword,
        appId: irccCaseForm.appId,
        applicationNumber: irccCaseForm.applicationNumber || null,
        principalApplicant: irccCaseForm.principalApplicant || null,
        receiveEmail: irccCaseForm.receiveEmail || null,
        senderMode: irccCaseForm.senderMode,
        isEnabled: irccCaseForm.isEnabled,
        emailNotificationsEnabled: irccCaseForm.emailNotificationsEnabled,
        smtpConfig: irccCaseForm.senderMode === "custom"
          ? {
              fromEmail: irccCaseForm.smtpFromEmail,
              host: irccCaseForm.smtpHost,
              port: Number(irccCaseForm.smtpPort),
              useSsl: irccCaseForm.smtpUseSsl,
              password: irccCaseForm.smtpPassword,
            }
          : null,
      };
      const result = await requestJson<{
        case: IrccCase;
        initialQueryJob?: { jobId: number; status: IrccQueryJob["status"] } | null;
      }>("/api/ircc/cases", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setIrccCaseForm(createEmptyIrccCaseForm(user?.email ?? ""));
      setIrccApplications([]);
      setSelectedCaseId(null);
      setSelectedIrccCaseId(result.case.id);
      setSelectedKoreaCaseId(null);
      setIsCreatingProfile(false);
      await loadIrccCases();
      if (result.initialQueryJob) {
        const job = await waitForIrccQueryJob(result.initialQueryJob.jobId, (status) => {
          showMessage(status === "queued" ? t("irccQueued") : t("irccQuerying"));
        });
        await loadIrccCases();
        await loadIrccHistory(result.case.id);
        if (!job || (job.status !== "succeeded" && job.status !== "failed")) {
          showMessage(job?.status === "queued" ? t("irccQueued") : t("irccQuerying"));
          return;
        }
        const queryResult = job.result;
        showMessage(
          queryResult?.success
            ? (queryResult.changed ? t("irccChanged") : t("irccUnchanged"))
            : (job.errorMessage || queryResult?.error || t("requestFailed")),
        );
        return;
      }
      showMessage(t("caseCreated"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function saveKoreaCase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsBusy(true);
    showMessage("");
    try {
      const payload = {
        displayName: koreaCaseForm.displayName,
        passportNumber: koreaCaseForm.passportNumber,
        englishName: koreaCaseForm.englishName,
        birthDate: koreaCaseForm.birthDate,
        receiveEmail: koreaCaseForm.receiveEmail || null,
        senderMode: koreaCaseForm.senderMode,
        isEnabled: koreaCaseForm.isEnabled,
        emailNotificationsEnabled: koreaCaseForm.emailNotificationsEnabled,
        smtpConfig: koreaCaseForm.senderMode === "custom"
          ? {
              fromEmail: koreaCaseForm.smtpFromEmail,
              host: koreaCaseForm.smtpHost,
              port: Number(koreaCaseForm.smtpPort),
              useSsl: koreaCaseForm.smtpUseSsl,
              password: koreaCaseForm.smtpPassword,
            }
          : null,
      };
      const result = await requestJson<{
        case: KoreaCase;
        initialQueryJob?: { jobId: number; status: KoreaQueryJob["status"] } | null;
      }>("/api/korea/cases", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setKoreaCaseForm(createEmptyKoreaCaseForm(user?.email ?? ""));
      setSelectedCaseId(null);
      setSelectedIrccCaseId(null);
      setSelectedKoreaCaseId(result.case.id);
      setIsCreatingProfile(false);
      await loadKoreaCases();
      if (result.initialQueryJob) {
        const job = await waitForKoreaQueryJob(result.initialQueryJob.jobId, (status) => {
          showMessage(status === "queued" ? t("koreaQueued") : t("koreaQuerying"));
        });
        await loadKoreaCases();
        await loadKoreaHistory(result.case.id);
        if (!job || (job.status !== "succeeded" && job.status !== "failed")) {
          showMessage(job?.status === "queued" ? t("koreaQueued") : t("koreaQuerying"));
          return;
        }
        const queryResult = job.result;
        showMessage(
          queryResult?.success
            ? (queryResult.changed ? t("koreaChanged") : t("koreaUnchanged"))
            : (job.errorMessage || queryResult?.error || t("requestFailed")),
        );
        return;
      }
      showMessage(t("caseCreated"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function runTest(caseId: number) {
    setIsBusy(true);
    showMessage(t("queryInProgress"));
    try {
      const payload = await requestJson<{ jobId: number; status: QueryJob["status"] }>(`/api/cases/${caseId}/test-query`, {
        method: "POST",
        body: "{}",
      });
      const job = await waitForQueryJob(payload.jobId, (status) => {
        if (status === "queued") {
          showMessage(t("queryQueued"));
        } else if (status === "running") {
          showMessage(t("queryInProgress"));
        }
      });
      await loadCases();
      await loadHistory(caseId);
      if (!job || (job.status !== "succeeded" && job.status !== "failed")) {
        showMessage(job?.status === "queued" ? t("queryQueued") : t("queryInProgress"));
        return;
      }
      const result = job.result;
      showMessage(
        result?.success
          ? (result.changed ? t("fastQueryChanged") : t("fastQueryUnchanged"))
          : (job.errorMessage || result?.error || t("requestFailed")),
      );
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function sendTestEmail(caseId: number) {
    setIsBusy(true);
    showMessage(t("testEmailSending"));
    try {
      await requestJson<{ success: boolean; error: string }>(`/api/cases/${caseId}/test-email`, {
        method: "POST",
        body: "{}",
      });
      showMessage(t("testEmailSent"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function runIrccTest(caseId: number) {
    setIsBusy(true);
    showMessage(t("irccQuerying"));
    try {
      const payload = await requestJson<{ jobId: number; status: IrccQueryJob["status"] }>(`/api/ircc/cases/${caseId}/test-query`, {
        method: "POST",
        body: "{}",
      });
      const job = await waitForIrccQueryJob(payload.jobId, (status) => {
        showMessage(status === "queued" ? t("irccQueued") : t("irccQuerying"));
      });
      await loadIrccCases();
      await loadIrccHistory(caseId);
      if (!job || (job.status !== "succeeded" && job.status !== "failed")) {
        showMessage(job?.status === "queued" ? t("irccQueued") : t("irccQuerying"));
        return;
      }
      const result = job.result;
      showMessage(
        result?.success
          ? (result.changed ? t("irccChanged") : t("irccUnchanged"))
          : (job.errorMessage || result?.error || t("requestFailed")),
      );
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function sendIrccTestEmail(caseId: number) {
    setIsBusy(true);
    showMessage(t("irccTestEmailSending"));
    try {
      await requestJson<{ success: boolean; error: string }>(`/api/ircc/cases/${caseId}/test-email`, {
        method: "POST",
        body: "{}",
      });
      showMessage(t("irccTestEmailSent"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function runKoreaTest(caseId: number) {
    setIsBusy(true);
    showMessage(t("koreaQuerying"));
    try {
      const payload = await requestJson<{ jobId: number; status: KoreaQueryJob["status"] }>(`/api/korea/cases/${caseId}/test-query`, {
        method: "POST",
        body: "{}",
      });
      const job = await waitForKoreaQueryJob(payload.jobId, (status) => {
        showMessage(status === "queued" ? t("koreaQueued") : t("koreaQuerying"));
      });
      await loadKoreaCases();
      await loadKoreaHistory(caseId);
      if (!job || (job.status !== "succeeded" && job.status !== "failed")) {
        showMessage(job?.status === "queued" ? t("koreaQueued") : t("koreaQuerying"));
        return;
      }
      const result = job.result;
      showMessage(
        result?.success
          ? (result.changed ? t("koreaChanged") : t("koreaUnchanged"))
          : (job.errorMessage || result?.error || t("requestFailed")),
      );
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function sendKoreaTestEmail(caseId: number) {
    setIsBusy(true);
    showMessage(t("koreaTestEmailSending"));
    try {
      await requestJson<{ success: boolean; error: string }>(`/api/korea/cases/${caseId}/test-email`, {
        method: "POST",
        body: "{}",
      });
      showMessage(t("koreaTestEmailSent"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function toggleIrccEmailPush(targetCase: IrccCase) {
    setIsBusy(true);
    showMessage("");
    try {
      await requestJson<{ case: IrccCase }>(`/api/ircc/cases/${targetCase.id}`, {
        method: "PATCH",
        body: JSON.stringify({ emailNotificationsEnabled: !targetCase.emailNotificationsEnabled }),
      });
      await loadIrccCases();
      showMessage(!targetCase.emailNotificationsEnabled ? t("updatePushEnabled") : t("updatePushDisabled"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function toggleKoreaEmailPush(targetCase: KoreaCase) {
    setIsBusy(true);
    showMessage("");
    try {
      await requestJson<{ case: KoreaCase }>(`/api/korea/cases/${targetCase.id}`, {
        method: "PATCH",
        body: JSON.stringify({ emailNotificationsEnabled: !targetCase.emailNotificationsEnabled }),
      });
      await loadKoreaCases();
      showMessage(!targetCase.emailNotificationsEnabled ? t("updatePushEnabled") : t("updatePushDisabled"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function stopKoreaAutomaticQuery(targetCase: KoreaCase) {
    setIsBusy(true);
    showMessage("");
    try {
      await requestJson<{ case: KoreaCase }>(`/api/korea/cases/${targetCase.id}`, {
        method: "PATCH",
        body: JSON.stringify({ isEnabled: false }),
      });
      await loadKoreaCases();
      showMessage(t("automaticQueryStopped"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function toggleIrccAutomaticQuery(targetCase: IrccCase) {
    setIsBusy(true);
    showMessage("");
    const nextEnabled = !targetCase.isEnabled;
    try {
      await requestJson<{ case: IrccCase }>(`/api/ircc/cases/${targetCase.id}`, {
        method: "PATCH",
        body: JSON.stringify({ isEnabled: nextEnabled }),
      });
      await loadIrccCases();
      showMessage(nextEnabled ? t("automaticQueryStarted") : t("automaticQueryStopped"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function toggleEmailPush(targetCase: CeacCase) {
    setIsBusy(true);
    showMessage("");
    try {
      await requestJson<{ case: CeacCase }>(`/api/cases/${targetCase.id}`, {
        method: "PATCH",
        body: JSON.stringify({ emailNotificationsEnabled: !targetCase.emailNotificationsEnabled }),
      });
      await loadCases();
      showMessage(!targetCase.emailNotificationsEnabled ? t("updatePushEnabled") : t("updatePushDisabled"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function stopAutomaticQuery(targetCase: CeacCase) {
    setIsBusy(true);
    showMessage("");
    try {
      await requestJson<{ case: CeacCase }>(`/api/cases/${targetCase.id}`, {
        method: "PATCH",
        body: JSON.stringify({ isEnabled: false }),
      });
      await loadCases();
      showMessage(t("automaticQueryStopped"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function savePassportSlotMonitor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedCase) {
      return;
    }
    setIsBusy(true);
    showMessage("");
    try {
      const payload = await requestJson<{ monitor: PassportSlotMonitor }>(`/api/cases/${selectedCase.id}/passport-slot-monitor`, {
        method: "PUT",
        body: JSON.stringify({
          identifier: passportSlotIdentifier,
          isEnabled: passportSlotMonitor?.isEnabled ?? true,
          emailNotificationsEnabled: passportSlotMonitor?.emailNotificationsEnabled ?? true,
        }),
      });
      setPassportSlotMonitor(payload.monitor);
      setPassportSlotIdentifier(payload.monitor.identifier);
      await loadPassportSlotMonitor(selectedCase.id);
      showMessage(t("passportSlotSaved"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function togglePassportSlotMonitor(targetCase: CeacCase, targetMonitor: PassportSlotMonitor) {
    setIsBusy(true);
    showMessage("");
    try {
      const payload = await requestJson<{ monitor: PassportSlotMonitor }>(`/api/cases/${targetCase.id}/passport-slot-monitor`, {
        method: "PATCH",
        body: JSON.stringify({ isEnabled: !targetMonitor.isEnabled }),
      });
      setPassportSlotMonitor(payload.monitor);
      showMessage(!targetMonitor.isEnabled ? t("passportSlotEnabled") : t("passportSlotDisabled"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function confirmPassportSlotBooked(targetCase: CeacCase, targetMonitor: PassportSlotMonitor) {
    setIsBusy(true);
    showMessage("");
    try {
      const payload = await requestJson<{ monitor: PassportSlotMonitor }>(`/api/cases/${targetCase.id}/passport-slot-monitor`, {
        method: "PATCH",
        body: JSON.stringify({ isEnabled: false }),
      });
      setPassportSlotMonitor(payload.monitor);
      showMessage(t("passportSlotBookedStopped"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function togglePassportSlotEmailNotifications(targetCase: CeacCase, targetMonitor: PassportSlotMonitor) {
    setIsBusy(true);
    showMessage("");
    try {
      const payload = await requestJson<{ monitor: PassportSlotMonitor }>(`/api/cases/${targetCase.id}/passport-slot-monitor`, {
        method: "PATCH",
        body: JSON.stringify({ emailNotificationsEnabled: !targetMonitor.emailNotificationsEnabled }),
      });
      setPassportSlotMonitor(payload.monitor);
      showMessage(!targetMonitor.emailNotificationsEnabled ? t("passportSlotEmailEnabled") : t("passportSlotEmailDisabled"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function runPassportSlotQuery(caseId: number) {
    setIsBusy(true);
    showMessage(t("passportSlotQuerying"));
    try {
      const payload = await requestJson<{ jobId: number; status: QueryJob["status"] }>(`/api/cases/${caseId}/passport-slot-monitor/test-query`, {
        method: "POST",
        body: "{}",
      });
      const job = await waitForQueryJob(payload.jobId, (status) => {
        if (status === "queued") {
          showMessage(t("passportSlotQueued"));
        } else if (status === "running") {
          showMessage(t("passportSlotQuerying"));
        }
      });
      await loadPassportSlotMonitor(caseId);
      await loadCases();
      if (!job || (job.status !== "succeeded" && job.status !== "failed")) {
        showMessage(job?.status === "queued" ? t("passportSlotQueued") : t("passportSlotQuerying"));
        return;
      }
      const result = job.result;
      if (!result?.success) {
        showMessage(job.errorMessage || result?.error || t("requestFailed"));
        return;
      }
      if (result.slotStatus === "not_eligible") {
        showMessage(t("passportSlotNotEligible"));
      } else if (result.slotStatus === "no_slot") {
        showMessage(t("passportSlotNoSlot"));
      } else if ((result.slotCount ?? 0) > 0) {
        showMessage(result.changed ? t("passportSlotChanged") : t("passportSlotFound"));
      } else {
        showMessage(t("passportSlotNotFound"));
      }
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function sendPassportSlotTestEmail(caseId: number) {
    setIsBusy(true);
    showMessage(t("passportSlotTestEmailSending"));
    try {
      await requestJson<{ success: boolean; error: string }>(`/api/cases/${caseId}/passport-slot-monitor/test-email`, {
        method: "POST",
        body: "{}",
      });
      showMessage(t("passportSlotTestEmailSent"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function updateWorkerPriority(userId: number, workerPriority: number) {
    setIsBusy(true);
    showMessage("");
    try {
      await requestJson<{ user: AdminUser }>(`/api/admin/users/${userId}/worker-priority`, {
        method: "PATCH",
        body: JSON.stringify({ workerPriority }),
      });
      await loadAdminData();
      showMessage(t("workerPrioritySaved"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function updateAccountTier(userId: number, accountTier: AccountTier) {
    setIsBusy(true);
    showMessage("");
    try {
      await requestJson<{ user: AdminUser }>(`/api/admin/users/${userId}/account-tier`, {
        method: "PATCH",
        body: JSON.stringify({ accountTier }),
      });
      await loadAdminData();
      showMessage(t("accountTierSaved"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function restoreCeacAutoQuery(caseId: number) {
    setIsBusy(true);
    showMessage("");
    try {
      await requestJson<{ case: CeacCase }>(`/api/admin/cases/${caseId}/restore-ceac-auto-query`, {
        method: "POST",
        body: "{}",
      });
      await loadAdminData();
      await loadCases();
      showMessage(t("ceacAutoQueryRestored"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("requestFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function moveProfile(profileType: "ceac" | "ircc" | "korea", profileId: number, direction: "up" | "down") {
    const currentIndex = orderedProfiles.findIndex((item) => item.profileType === profileType && item.id === profileId);
    const targetIndex = direction === "up" ? currentIndex - 1 : currentIndex + 1;
    if (currentIndex < 0 || targetIndex < 0 || targetIndex >= orderedProfiles.length) {
      return;
    }
    const nextProfiles = [...orderedProfiles];
    [nextProfiles[currentIndex], nextProfiles[targetIndex]] = [nextProfiles[targetIndex], nextProfiles[currentIndex]];
    setIsBusy(true);
    showMessage("");
    try {
      await requestJson<{ ok: boolean }>("/api/profiles/order", {
        method: "PATCH",
        body: JSON.stringify({
          profiles: nextProfiles.map((item) => ({ profileType: item.profileType, id: item.id })),
        }),
      });
      await Promise.all([loadCases(), loadIrccCases(), loadKoreaCases()]);
      showMessage(t("profileOrderSaved"));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : t("profileOrderFailed"));
    } finally {
      setIsBusy(false);
    }
  }

  async function removeCase(caseId: number) {
    await requestJson<{ ok: boolean }>(`/api/cases/${caseId}`, { method: "DELETE", body: "{}" });
    setSelectedCaseId(null);
    await loadCases();
  }

  async function removeIrccCase(caseId: number) {
    await requestJson<{ ok: boolean }>(`/api/ircc/cases/${caseId}`, { method: "DELETE", body: "{}" });
    setSelectedIrccCaseId(null);
    setSelectedCaseId(null);
    await loadIrccCases();
  }

  async function removeKoreaCase(caseId: number) {
    await requestJson<{ ok: boolean }>(`/api/korea/cases/${caseId}`, { method: "DELETE", body: "{}" });
    setSelectedKoreaCaseId(null);
    setSelectedIrccCaseId(null);
    setSelectedCaseId(null);
    await loadKoreaCases();
  }

  if (!user) {
    return (
      <main className="auth-shell">
        <div className="auth-tools">
          <LanguageButton languageMode={languageMode} setLanguageMode={setLanguageMode} />
          <ThemeButton themeMode={themeMode} setThemeMode={setThemeMode} t={t} />
        </div>
        <div className="auth-header">
          <img className="brand-mark" src="/favicon.svg" alt="CEACStatusBot" />
          <h1 className="display-md">CEACStatusBot</h1>
          <p className="body">{t("appSubtitle")}</p>
        </div>
        <section className="auth-panel">
          <form className="stack" onSubmit={submitAuth}>
            <div className="segmented">
              <button type="button" className={authMode === "login" ? "selected" : ""} onClick={() => setAuthMode("login")}>
                {t("login")}
              </button>
              <button type="button" className={authMode === "register" ? "selected" : ""} onClick={() => setAuthMode("register")}>
                {t("register")}
              </button>
            </div>
            <label>
              {t("email")}
              <input value={authEmail} onChange={(event) => setAuthEmail(event.target.value)} type="email" required autoComplete="username" />
            </label>
            <label>
              {authMode === "forgot" ? t("resetPassword") : t("password")}
              <input
                value={authPassword}
                onChange={(event) => setAuthPassword(event.target.value)}
                type="password"
                required
                minLength={8}
                autoComplete={authMode === "login" ? "current-password" : "new-password"}
              />
            </label>
            {authMode === "login" && (
              <div className="auth-options">
                <div className="auth-remember-options">
                  <label className="checkbox">
                    <input type="checkbox" checked={rememberAccount} onChange={(event) => setRememberAccount(event.target.checked)} />
                    <span className="body-sm">{t("rememberAccount")}</span>
                  </label>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={rememberPassword}
                      onChange={(event) => {
                        setRememberPassword(event.target.checked);
                        if (event.target.checked) {
                          setRememberAccount(true);
                        }
                      }}
                    />
                    <span className="body-sm">{t("rememberPassword")}</span>
                  </label>
                  {rememberPassword && <p className="field-hint">{t("rememberPasswordWarning")}</p>}
                </div>
                <button type="button" className="text-button" onClick={() => { setAuthMode("forgot"); showMessage(""); }}>
                  {t("forgotPassword")}
                </button>
              </div>
            )}
            {(authMode === "register" || authMode === "forgot") && (
              <label>
                {t("verificationCode")}
                <div className="inline-field">
                  <input
                    value={authMode === "forgot" ? resetCode : registerCode}
                    onChange={(event) => authMode === "forgot" ? setResetCode(event.target.value) : setRegisterCode(event.target.value)}
                    required
                  />
                  <button type="button" className="button secondary" onClick={sendCode} disabled={isBusy}>
                    {t("send")}
                  </button>
                </div>
              </label>
            )}
            {authMode === "register" && (
              <div className="terms-box">
                <div className="support-title">
                  <Shield size={16} />
                  <span>{t("termsTitle")}</span>
                </div>
                <p>{t("termsBody")}</p>
                <button
                  type="button"
                  className="text-button terms-link-button"
                  onClick={() => {
                    setAcceptedTerms(true);
                    setIsTermsDialogOpen(true);
                  }}
                >
                  {t("viewTerms")}
                </button>
                <label className="checkbox">
                  <input type="checkbox" checked={acceptedTerms} onChange={(event) => setAcceptedTerms(event.target.checked)} required />
                  <span className="body-sm">{t("acceptTerms")}</span>
                </label>
              </div>
            )}
            {authMode === "forgot" && (
              <label>
                {languageMode === "zh" ? "确认新密码" : "Confirm new password"}
                <input
                  value={resetConfirmPassword}
                  onChange={(event) => setResetConfirmPassword(event.target.value)}
                  type="password"
                  required
                  minLength={8}
                  autoComplete="new-password"
                />
              </label>
            )}
            <button className="button primary" disabled={isBusy}>
              {authMode === "login" ? t("loginAction") : authMode === "register" ? t("registerAction") : t("resetAction")}
            </button>
            {authMode === "forgot" && (
              <button type="button" className="text-button centered" onClick={() => { setAuthMode("login"); showMessage(""); }}>
                {t("login")}
              </button>
            )}
            {activeMessage && <p className="notice">{activeMessage}</p>}
          </form>
        </section>
        <PublicNoticePanel t={t} />
        <SiteFooter t={t} />
        {isTermsDialogOpen && <TermsDialog t={t} languageMode={languageMode} onClose={() => setIsTermsDialogOpen(false)} />}
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="top-nav">
        <div className="top-nav-main">
          <div className="brand-lockup">
            <img className="brand-mark" src="/favicon.svg" alt="" />
            <span className="brand-name">CEACStatusBot</span>
          </div>
        </div>
        <nav className="nav-actions" aria-label="Primary">
          <button className={`nav-tab ${viewMode === "dashboard" ? "active" : ""}`} onClick={() => setViewMode("dashboard")}>
            <UserRound size={16} /> {t("dashboard")}
          </button>
          <button className={`nav-tab ${viewMode === "profile" ? "active" : ""}`} onClick={() => setViewMode("profile")}>
            <UserRound size={16} /> {t("personalInfo")}
          </button>
          {user.role === "admin" && (
            <button
              className={`nav-tab ${viewMode === "admin" ? "active" : ""}`}
              onClick={() => {
                setViewMode("admin");
                void loadAdminData();
                void loadAdminQueueData();
              }}
            >
              <Shield size={16} /> {t("admin")}
            </button>
          )}
        </nav>
        <div className="utility-actions">
          <LanguageButton languageMode={languageMode} setLanguageMode={setLanguageMode} />
          <ThemeButton themeMode={themeMode} setThemeMode={setThemeMode} t={t} />
          <button className="button tertiary icon-only" onClick={logout} title={t("logoutTitle")} aria-label={t("logoutTitle")}>
            <LogOut size={16} />
          </button>
        </div>
      </header>

      <section className="workspace">
        <header className="page-header">
          <div>
            <p className="eyebrow" style={{ color: 'var(--primary-hover)' }}>{t("currentLogin")}: {user.email}</p>
            <h1 className="headline">
              {viewMode === "admin" ? t("adminTitle") : viewMode === "profile" ? t("personalInfo") : t("statusMonitoring")}
            </h1>
          </div>
          {activeMessage && <p className="notice">{activeMessage}</p>}
        </header>

        {viewMode === "dashboard" ? (
          <div className="dashboard-layout">
            <div className="stack">
              <section className="panel">
                <div className="panel-title">
                  <h2 className="headline">{t("caseList")}</h2>
                  <button className="button secondary" title={t("caseName")} onClick={() => { setIsCreatingProfile(true); setSelectedCaseId(null); setSelectedIrccCaseId(null); setSelectedKoreaCaseId(null); setCaseForm(createEmptyCaseForm(user.email)); setIrccCaseForm(createEmptyIrccCaseForm(user.email)); setKoreaCaseForm(createEmptyKoreaCaseForm(user.email)); }}>
                    <Plus size={16} /> {t("newProfile")}
                  </button>
                </div>
                <div className="case-list">
                  {orderedProfiles.map((profile, index) => {
                    const item = profile.case;
                    const isCeac = profile.profileType === "ceac";
                    const isKorea = profile.profileType === "korea";
                    const isSelected = isCeac
                      ? selectedCaseId === item.id && selectedIrccCaseId === null && selectedKoreaCaseId === null
                      : isKorea
                        ? selectedKoreaCaseId === item.id
                        : selectedIrccCaseId === item.id;
                    const statusNode = profile.profileType === "ceac"
                      ? <span className={getStatusBadgeClass(profile.case.lastStatus)}>{profile.case.lastStatus ?? t("waitFirstQuery")}</span>
                      : profile.profileType === "ircc"
                        ? (
                            <div className="case-status-stack">
                              <span
                                className={getIrccToneBadgeClass(profile.case.statusOverview?.tone)}
                                title={profile.case.statusOverview ? formatIrccCompactHeadline(profile.case.statusOverview, languageMode) : t("waitFirstQuery")}
                              >
                                {profile.case.statusOverview ? formatIrccCompactHeadline(profile.case.statusOverview, languageMode) : t("waitFirstQuery")}
                              </span>
                            </div>
                          )
                        : <span className={getStatusBadgeClass(profile.case.lastStatus)}>{profile.case.lastStatus || t("waitFirstQuery")}</span>;
                    const caseMeta = profile.profileType === "ceac"
                      ? `${t("countryUnitedStates")} · ${profile.case.applicationNum || t("missingCaseNumber")}`
                      : profile.profileType === "ircc"
                        ? `${t("countryCanada")} · ${profile.case.applicationNumber || profile.case.appId}`
                        : `${t("countryKorea")} · ${profile.case.lastApplicationNo || profile.case.passportNumber}`;
                    return (
                      <div
                        key={`${profile.profileType}-${item.id}`}
                        className={`case-row hover-card ${isSelected ? "selected" : ""}`}
                        onClick={() => {
                          setIsCreatingProfile(false);
                          if (isCeac) {
                            setSelectedIrccCaseId(null);
                            setSelectedKoreaCaseId(null);
                            setSelectedCaseId(item.id);
                          } else if (isKorea) {
                            setSelectedCaseId(null);
                            setSelectedIrccCaseId(null);
                            setSelectedKoreaCaseId(item.id);
                          } else {
                            setSelectedCaseId(null);
                            setSelectedKoreaCaseId(null);
                            setSelectedIrccCaseId(item.id);
                          }
                        }}
                      >
                        <div className="case-row-icon">
                          {isCeac ? <Landmark size={20} /> : isKorea ? <LucideMap size={20} /> : <TreePine size={20} />}
                        </div>
                        <div className="case-info">
                          <div className="case-name">{item.displayName}</div>
                          <div className="case-meta">{caseMeta}</div>
                        </div>
                        <div className="case-row-actions">
                          <div className="profile-status-slot">{statusNode}</div>
                          <div className="case-order-buttons" aria-label={languageMode === "zh" ? "调整档案顺序" : "Reorder profiles"}>
                            <button
                              type="button"
                              className="button tertiary icon-only compact"
                              title={t("moveProfileUp")}
                              aria-label={t("moveProfileUp")}
                              disabled={isBusy || index === 0}
                              onClick={(event) => {
                                event.stopPropagation();
                                void moveProfile(profile.profileType, item.id, "up");
                              }}
                            >
                              <ArrowUp size={14} />
                            </button>
                            <button
                              type="button"
                              className="button tertiary icon-only compact"
                              title={t("moveProfileDown")}
                              aria-label={t("moveProfileDown")}
                              disabled={isBusy || index === orderedProfiles.length - 1}
                              onClick={(event) => {
                                event.stopPropagation();
                                void moveProfile(profile.profileType, item.id, "down");
                              }}
                            >
                              <ArrowDown size={14} />
                            </button>
                          </div>
                          <ChevronRight className="case-chevron" size={18} />
                        </div>
                      </div>
                    );
                  })}
                  {orderedProfiles.length === 0 && (
                    <div className="empty-state">
                      <div className="empty-state-icon"><FolderOpen size={24} /></div>
                      <h3 className="headline">{t("noCases")}</h3>
                    </div>
                  )}
                </div>
              </section>
              <SupportPanel t={t} />
              <PublicNoticePanel t={t} />
            </div>

            <div className="stack">
              {selectedKoreaCase ? (
                <KoreaCaseDetail
                  targetCase={selectedKoreaCase}
                  history={koreaHistory}
                  runQuery={runKoreaTest}
                  sendTestEmail={sendKoreaTestEmail}
                  removeCase={removeKoreaCase}
                  toggleEmailPush={toggleKoreaEmailPush}
                  stopAutomaticQuery={stopKoreaAutomaticQuery}
                  isBusy={isBusy}
                  t={t}
                  languageMode={languageMode}
                />
              ) : selectedIrccCase ? (
                <IrccCaseDetail
                  targetCase={selectedIrccCase}
                  history={irccHistory}
                  runQuery={runIrccTest}
                  sendTestEmail={sendIrccTestEmail}
                  removeCase={removeIrccCase}
                  toggleEmailPush={toggleIrccEmailPush}
                  toggleAutomaticQuery={toggleIrccAutomaticQuery}
                  isBusy={isBusy}
                  t={t}
                  languageMode={languageMode}
                />
              ) : selectedCaseId === null ? (
                <section className="panel">
                  <div className="panel-title">
                    <div>
                      <h2 className="headline">{t("statusMonitoring")}</h2>
                      <p className="form-intro">{t("officialIntro")}</p>
                    </div>
                  </div>
                  <NewProfileForm
                    country={newProfileCountry}
                    setCountry={setNewProfileCountry}
                    caseForm={caseForm}
                    setCaseForm={setCaseForm}
                    saveCase={saveCase}
                    irccCaseForm={irccCaseForm}
                    setIrccCaseForm={setIrccCaseForm}
                    saveIrccCase={saveIrccCase}
                    koreaCaseForm={koreaCaseForm}
                    setKoreaCaseForm={setKoreaCaseForm}
                    saveKoreaCase={saveKoreaCase}
                    discoverIrccApplications={discoverIrccApplications}
                    irccApplications={irccApplications}
                    isBusy={isBusy}
                    t={t}
                    languageMode={languageMode}
                  />
                </section>
              ) : selectedCase ? (
                <>
                  <section className="panel">
                    <div className="panel-title">
                      <h2 className="headline">{selectedCase.displayName}</h2>
                      <div className="row-actions">
                        <button className="button secondary" onClick={() => runTest(selectedCase.id)} disabled={isBusy}>
                          <Activity size={16} /> {t("fastQuery")}
                        </button>
                        <button className="button secondary" onClick={() => sendTestEmail(selectedCase.id)} disabled={isBusy || history.length === 0}>
                          <Mail size={16} /> {t("testEmail")}
                        </button>
                        <button className="icon-button danger" onClick={() => { if (confirm(t("confirmDelete"))) void removeCase(selectedCase.id); }}>
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </div>
                    
                    <div className="stack" style={{ marginBottom: "24px" }}>
                      {isIssuedStatus(selectedCase.lastStatus) && selectedCase.isEnabled && (
                        <div className="notice action-notice">
                          <span>{t("issuedSlowQueryNotice")}</span>
                          <button className="button secondary" onClick={() => stopAutomaticQuery(selectedCase)} disabled={isBusy}>
                            {t("stopAutomaticQuery")}
                          </button>
                        </div>
                      )}
                      {selectedCase.ceacAutoLockedByPassportSlot && (
                        <div className="notice">
                          {t("ceacAutoLockedByPassportSlot")}
                        </div>
                      )}
                      {selectedCase.lastCeacError && (
                        <div className="notice">
                          <strong>{t("lastCeacError")}：</strong>{selectedCase.lastCeacError}
                          {selectedCase.ceacConsecutiveErrorCount > 0 && (
                            <span> · {t("ceacConsecutiveErrors")}：{selectedCase.ceacConsecutiveErrorCount}</span>
                          )}
                        </div>
                      )}
                      <div className="two-col metric-grid">
                        <Metric icon={<MapPin size={14} />} label={t("locationMetric")} value={selectedCase.location} />
                        <Metric icon={<FileText size={14} />} label={`${t("applicationId")} / ${t("passport")}`} value={`${selectedCase.applicationNum} / ${selectedCase.passportNumber}`} />
                      </div>
                      <div className="two-col metric-grid">
                        <Metric icon={<Mail size={14} />} label={t("notifyEmail")} value={selectedCase.receiveEmail} />
                        <Metric icon={<Activity size={14} />} label={t("status")}>
                          <span className={getStatusBadgeClass(selectedCase.lastStatus, "metric-status")}>
                            {selectedCase.lastStatus || t("noStatus")}
                          </span>
                        </Metric>
                      </div>
                      <div className="two-col metric-grid">
                        <Metric icon={<Clock size={14} />} label={t("lastCheckedAt")} value={formatTime(selectedCase.lastCheckedAt, languageMode)} />
                        <Metric icon={<Activity size={14} />} label={t("lastCheckMode")} value={formatTriggerType(selectedCase.lastTriggerType, t)} />
                      </div>
                      <div className="two-col metric-grid">
                        <Metric icon={<Clock size={14} />} label={t("nextCheckAt")} value={formatTime(selectedCase.nextCheckAt, languageMode)} />
                        <Metric icon={<Bell size={14} />} label={t("emailPushSetting")} value={selectedCase.emailNotificationsEnabled ? t("emailPushOn") : t("emailPushOff")} />
                      </div>
                      <div className="settings-row">
                        <label className="checkbox">
                          <input
                            type="checkbox"
                            checked={selectedCase.emailNotificationsEnabled}
                            onChange={() => toggleEmailPush(selectedCase)}
                            disabled={isBusy}
                          />
                          <span className="body-sm">{t("emailPushSetting")}</span>
                        </label>
                        <span className={`status-badge ${selectedCase.emailNotificationsEnabled ? "success" : ""}`}>
                          {selectedCase.emailNotificationsEnabled ? t("emailPushOn") : t("emailPushOff")}
                        </span>
                      </div>
                    </div>
                  </section>

                  <PassportSlotMonitorPanel
                    selectedCase={selectedCase}
                    monitor={passportSlotMonitor}
                    history={passportSlotHistory}
                    identifier={passportSlotIdentifier}
                    setIdentifier={setPassportSlotIdentifier}
                    saveMonitor={savePassportSlotMonitor}
                    toggleMonitor={togglePassportSlotMonitor}
                    toggleEmailNotifications={togglePassportSlotEmailNotifications}
                    confirmBooked={confirmPassportSlotBooked}
                    runQuery={runPassportSlotQuery}
                    sendTestEmail={sendPassportSlotTestEmail}
                    isBusy={isBusy}
                    t={t}
                    languageMode={languageMode}
                  />

                  <section className="panel">
                    <div className="panel-title">
                      <h2 className="subhead">{t("statusHistory")}</h2>
                      <History size={18} />
                    </div>
                    <div className="timeline">
                      {history.map((record) => (
                        <div key={record.id} className="timeline-item">
                          <div className="timeline-header">
                            <span className="timeline-time">{formatTime(record.fetchedAt, languageMode)}</span>
                            <span className={getStatusBadgeClass(record.status)}>{record.status}</span>
                          </div>
                          <div className="timeline-desc">{record.description}</div>
                        </div>
                      ))}
                      {history.length === 0 && (
                        <div className="empty-state">
                          <div className="empty-state-icon"><History size={24} /></div>
                          <p>{t("noHistory")}</p>
                        </div>
                      )}
                    </div>
                  </section>
                </>
              ) : null}
            </div>
          </div>
        ) : viewMode === "profile" ? (
          <ProfilePanel
            user={user}
            profileForm={profileForm}
            setProfileForm={setProfileForm}
            saveProfile={saveProfile}
            acceptCurrentTerms={acceptCurrentTerms}
            isBusy={isBusy}
            t={t}
            languageMode={languageMode}
          />
        ) : (
          <AdminPanel
            users={adminUsers}
            queryRuns={queryRuns}
            queryJobs={queryJobs}
            scheduledQueryJobs={scheduledQueryJobs}
            finishedQueryJobs={finishedQueryJobs}
            securityEvents={securityEvents}
            emailDeliveryLogs={emailDeliveryLogs}
            cases={adminCases}
            reload={loadAdminData}
            t={t}
            languageMode={languageMode}
            systemEmailConfig={systemEmailConfig}
            systemEmailForm={systemEmailForm}
            setSystemEmailForm={setSystemEmailForm}
            saveSystemEmail={saveSystemEmail}
            updateAccountTier={updateAccountTier}
            updateWorkerPriority={updateWorkerPriority}
            restoreCeacAutoQuery={restoreCeacAutoQuery}
            isBusy={isBusy}
          />
        )}
      </section>
      <SiteFooter t={t} />
    </main>
  );
}

function SupportPanel(props: { t: (key: TranslationKey) => string; compact?: boolean }) {
  return (
    <section className={`support-card ${props.compact ? "compact" : ""}`}>
      <div className="support-copy">
        <div className="support-title">
          <HeartHandshake size={16} />
          <span>{props.t("supportTitle")}</span>
        </div>
        <p>{props.t("supportBody")}</p>
        <p>{props.t("supportPremium")}</p>
        <p className="support-disclaimer">{props.t("supportDisclaimer")}</p>
        <img src="/support/buy-me-a-coffee.jpg" alt={props.t("supportTitle")} />
      </div>
    </section>
  );
}

function PublicNoticePanel(props: { t: (key: TranslationKey) => string }) {
  return (
    <section className="support-card compact">
      <div className="support-copy">
        <div className="support-title">
          <Shield size={16} />
          <span>{props.t("publicNoticeTitle")}</span>
        </div>
        <p>{props.t("publicNoticeBody")}</p>
        <p className="support-disclaimer">{props.t("publicNoticeDisclaimer")}</p>
      </div>
    </section>
  );
}

// Code mappings are extracted from the IRCC Portal frontend bundle in the HAR.
// IRCC may change these private frontend keys, so unknown codes are still shown raw.
const irccStatusCodeMap: Record<string, { zh: string; en: string }> = {
  A0: { zh: "", en: "" },
  A1: { zh: "IRCC 已收到你的申请。若有更新或需要更多信息，IRCC 会发送消息。", en: "We received your application. We will send you a message when there is an update or if we need more information from you." },
  A2: { zh: "已作出最终决定。请查看下方最终决定。", en: "A final decision has been made. Please see the final decision below." },
  A3: { zh: "你的申请已取消。", en: "Your application was cancelled." },
  A4: { zh: "申请处于暂停状态。", en: "On Hold" },
  A5: { zh: "档案不符合资格。", en: "Profile Ineligible" },
  A6: { zh: "档案已过期。", en: "Profile Expired" },
  A7: { zh: "已收到邀请。", en: "Invitation Received" },
  A8: { zh: "资料不完整。", en: "Incomplete" },
  A9: { zh: "因资料不完整而取消。", en: "Cancelled As Incomplete" },
  A10: { zh: "等待额外条件。", en: "Pending Additional Criteria" },
  A11: { zh: "我们正在处理你的申请。若有更新或需要更多信息，IRCC 会发送消息。", en: "We are processing your application. We will send you a message when there is an update or if we need more information from you." },
  A12: { zh: "你的申请已撤回。", en: "Your application was withdrawn." },
  A13: { zh: "你的申请已被视为放弃。请查看下方最终决定。", en: "Your application was abandoned. See the final decision below." },
  A14: { zh: "你的申请有延迟。请查看下方消息了解详情。", en: "There is a delay with your application. Check your messages below for details." },
  A16: { zh: "你的申请有延迟。IRCC 会通过信件或邮件发送详情。", en: "There is a delay with your application. We will send you a letter or email with details." },
  A17: { zh: "你的申请有延迟。", en: "There is a delay with your application." },
  A18: { zh: "你的申请已完成。", en: "Your application was completed." },
  A19: { zh: "IRCC 正在处理你的申请。若有更新、预约已安排或需要更多信息，IRCC 会发送消息。", en: "We are processing your application. We will send you a message when there is an update, an appointment has been scheduled or if we need more information from you." },
  A20: { zh: "你的难民申请已暂停。请查看下方消息。", en: "Your refugee claim has been suspended. Please check your messages below." },
  A21: { zh: "你的难民申请已有资格决定。该决定将会或已经发送给你。", en: "An eligibility decision has been made on your refugee claim. The decision will be or has been communicated to you." },
  SUBMITTED: { zh: "已提交", en: "Submitted" },
  IN_PROGRESS: { zh: "进行中", en: "In progress" },
  E0: { zh: "不适用。", en: "Not applicable." },
  E1: { zh: "申请正在处理中。IRCC 会在开始审查资格时发送消息。", en: "Your application is in progress. IRCC will message you when eligibility review starts." },
  E2: { zh: "IRCC 正在审查你是否符合资格要求。", en: "IRCC is reviewing whether you meet the eligibility requirements." },
  E3: { zh: "资格审查已通过，请查看最终决定。", en: "Eligibility review passed. Check the final decision." },
  E4: { zh: "资格审查未通过，请查看最终决定。", en: "Eligibility review did not pass. Check the final decision." },
  E5: { zh: "不适用。", en: "Not applicable." },
  M0: { zh: "不适用。", en: "Not applicable." },
  M1: { zh: "不需要体检；如有变化，IRCC 会发送消息。", en: "You do not need a medical exam. IRCC will message you if this changes." },
  M2: { zh: "IRCC 已要求体检，请查看消息。", en: "IRCC has requested a medical exam. Check your messages." },
  M3: { zh: "IRCC 正在审查体检结果。", en: "IRCC is reviewing your medical results." },
  M4: { zh: "体检结果已通过。", en: "Medical results passed." },
  M5: { zh: "体检结果未通过，请查看最终决定。", en: "Medical results did not pass. Check the final decision." },
  M6: { zh: "IRCC 未收到你所需体检的结果。请查看体检请求消息了解详情。", en: "We did not receive the results of your required medical exam. Check your medical exam request message below for details." },
  M7: { zh: "IRCC 已要求体检。IRCC 会通过信件或邮件发送详情。", en: "We have requested a medical exam. We will send you a letter or email with details." },
  M8: { zh: "IRCC 未收到你所需体检的结果。请查看体检请求消息了解详情。", en: "We did not receive the results of your required medical exam. Check your medical exam request message for details." },
  AD0: { zh: "不适用。", en: "Not applicable." },
  AD1: { zh: "不需要补充文件。", en: "No additional documents are needed." },
  AD2: { zh: "IRCC 需要补充文件，请查看消息。", en: "IRCC needs additional documents. Check your messages." },
  AD3: { zh: "补充文件已上传。", en: "Additional documents uploaded." },
  AD4: { zh: "补充文件已收到，正在审查。", en: "Additional documents received and under review." },
  AD5: { zh: "IRCC 需要补充文件来处理你的申请。IRCC 会通过信件或邮件发送详情。", en: "We need additional documents to process your application. We will send you a letter or email with details." },
  AD6: { zh: "IRCC 已收到你提供的补充文件。", en: "We have received the additional documents you provided." },
  IA0: { zh: "不适用。", en: "Not applicable." },
  IA1: { zh: "不需要面试；如有变化，IRCC 会发送消息。", en: "You do not need an interview. IRCC will message you if this changes." },
  IA2: { zh: "需要面试，请查看消息。", en: "An interview is required. Check your messages." },
  IA3: { zh: "面试已完成。", en: "Interview completed." },
  IA4: { zh: "面试已取消，请查看消息。", en: "Interview cancelled. Check your messages." },
  IA5: { zh: "面试已重新安排。请查看消息了解详情。", en: "Your interview was rescheduled. Check your messages for details." },
  IA6: { zh: "你没有参加已安排的面试。请查看面试请求消息了解详情。", en: "You did not attend your scheduled interview. Check your interview request message below for details." },
  IA7: { zh: "你需要参加面试。IRCC 会通过信件或邮件发送详情。", en: "You need to attend an interview. We will send you a letter or email with details." },
  IA8: { zh: "你没有参加已安排的面试。IRCC 会通过信件或邮件发送详情。", en: "You did not attend your scheduled interview. We will send you a letter or email with details." },
  IA9: { zh: "面试尚未安排；如有变化，IRCC 会发送消息。", en: "You have not yet been scheduled for an interview. We will send you a message if this changes." },
  IA10: { zh: "你已参加预约。如需再次见面，IRCC 会通知你。", en: "You have attended an appointment. We will advise if we need to see you again." },
  B0: { zh: "不适用。", en: "Not applicable." },
  B1: { zh: "不需要提供指纹；如有变化，IRCC 会发送消息。", en: "You do not need to give biometrics. IRCC will message you if this changes." },
  B2: { zh: "需要提供指纹，请查看消息。", en: "Biometrics are required. Check your messages." },
  B3: { zh: "指纹/生物信息已完成。", en: "Biometrics completed." },
  B5: { zh: "IRCC 尚未收到你的指纹。请查看生物信息请求消息了解详情。", en: "We have not received your fingerprints. Check your biometrics request message below for details." },
  B6: { zh: "IRCC 需要你的指纹来处理申请。IRCC 会通过信件或邮件发送详情。", en: "We need your fingerprints to process your application. We will send you a letter or email with details." },
  B7: { zh: "IRCC 尚未收到你的指纹。请查看生物信息请求消息了解详情。", en: "We have not received your fingerprints. Check your biometrics request message for details." },
  B8: { zh: "IRCC 不需要你的指纹。", en: "We do not need your fingerprints." },
  B9: { zh: "已完成。你已提供指纹；如有问题，IRCC 会联系你。", en: "Completed. You have provided your fingerprints. If there are any issues, you will be contacted." },
  BC0: { zh: "不适用。", en: "Not applicable." },
  BC1: { zh: "申请正在处理中。IRCC 会在开始背景调查时发送消息。", en: "Your application is in progress. IRCC will message you when the background check starts." },
  BC2: { zh: "IRCC 正在处理背景调查；如需更多信息会发送消息。", en: "IRCC is processing your background check and will message you if more information is needed." },
  BC3: { zh: "背景调查已完成。", en: "Background check completed." },
  BC4: { zh: "不适用。", en: "Not applicable." },
  FD0: { zh: "", en: "" },
  FD1: { zh: "申请正在处理中。最终决定作出后，IRCC 会发送消息。", en: "Your application is in progress. IRCC will message you once the final decision is made." },
  FD2: { zh: "申请已获批，请查看消息。", en: "Application approved. Check your messages." },
  FD3: { zh: "申请已被拒，请查看消息。", en: "Application refused. Check your messages." },
  FD4: { zh: "申请已撤回，请查看消息。", en: "Application withdrawn." },
  FD5: { zh: "申请已取消，请查看消息。", en: "Application cancelled. Check your messages." },
  FD6: { zh: "申请已获批。你需要提交有效护照以完成申请。请查看下方消息了解详情。", en: "Your application was approved. You need to send us your valid passport to finalize your application. Check your messages below for details." },
  FD7: { zh: "申请因资料不完整而取消。请查看下方消息了解详情。", en: "Your application was cancelled because it was incomplete. Check your messages below for details." },
  FD8: { zh: "申请无法撤回。请查看下方消息了解详情。", en: "Your application cannot be withdrawn. Check your messages below for details." },
  FD9: { zh: "申请已获批。你需要提交有效护照以完成申请。IRCC 会通过信件或邮件发送详情。", en: "Your application was approved. You need to send us your valid passport to finalize your application. We will send you a letter or email with details." },
  FD10: { zh: "申请已被拒。IRCC 会通过信件或邮件发送详情。", en: "We regret to inform you that your application was refused. We will send you a letter or email with details." },
  FD11: { zh: "申请已撤回。IRCC 会通过信件或邮件发送详情。", en: "Your application was withdrawn. We will send you a letter or email with details." },
  FD12: { zh: "申请无法撤回。IRCC 会通过信件或邮件发送详情。", en: "Your application cannot be withdrawn. We will send you a letter or email with details." },
  FD13: { zh: "已找到公民身份记录。请查看下方消息了解详情。", en: "A record of citizenship was found. Check your messages below for details." },
  FD14: { zh: "已找到公民身份记录。IRCC 会通过信件或邮件发送详情。", en: "A record of citizenship was found. We will send you a letter or email with details." },
  FD15: { zh: "未找到公民身份记录。请查看下方消息了解详情。", en: "A record of citizenship was not found. Check your messages below for details." },
  FD16: { zh: "未找到公民身份记录。IRCC 会通过信件或邮件发送详情。", en: "A record of citizenship was not found. We will send you a letter or email with details." },
  FD17: { zh: "申请已获批。IRCC 会通过信件或邮件发送详情。", en: "Your application was approved. We will send you a letter or email with details." },
  FD18: { zh: "申请已取消。IRCC 会发送包含详情的消息。", en: "Your application was cancelled. We will send you a message with details." },
  FD20: { zh: "IRCC 无法处理你的申请，因为该申请已被视为放弃。请查看下方消息了解详情。", en: "We cannot process your application because it was abandoned. Check your messages below for details." },
  FD21: { zh: "IRCC 无法处理你的申请，因为该申请已被视为放弃。IRCC 会通过信件或邮件发送详情。", en: "We cannot process your application because it was abandoned. We will send you a letter or email with details." },
  FD22: { zh: "你的难民申请不符合转交 IRB 的资格。", en: "We regret to inform you that your refugee claim is ineligible to be referred to the IRB." },
  FD23: { zh: "IRCC 很快会向你提供决定。", en: "You will be provided with a decision shortly." },
  FD24: { zh: "申请正在处理中。", en: "Your application is in progress." },
  PS0: { zh: "档案处理中", en: "Profile in progress" },
  PBT0: { zh: "", en: "" },
  PBT1: { zh: "预计剩余处理时间", en: "Estimated remaining processing time" },
  PBT2: { zh: "你的申请已撤回。", en: "Your application was withdrawn." },
  PBT3: { zh: "你的申请已完成。", en: "Your application was completed." },
  PBT4: { zh: "你的申请已取消。", en: "Your application was cancelled." },
  PBT5: { zh: "你的申请处理时间比通常更长。", en: "Your application is taking us longer than usual to process." },
  PBT6: { zh: "IRCC 已完成你的申请处理。", en: "We're done processing your application." },
  PBT7: { zh: "你的申请已被视为放弃。", en: "Your application was abandoned." },
  PBS0: { zh: "", en: "" },
  PBS1: { zh: "为帮助你估计 IRCC 何时可能作出决定，IRCC 已在你的账户中加入处理时间。", en: "To help you estimate when we could reach a decision on your application, we added a processing time to your account." },
  PBS2: { zh: "你可能暂时不会收到 IRCC 消息，这是正常情况。大多数申请进展会在接近预计完成日期时发生。", en: "You may not hear from us for a little while, this is normal. Most of the progress on your application happens closer to your estimated completion date." },
  PBS3: { zh: "请确保阅读消息并在 IRCC 要求时采取行动，这有助于推进申请处理。", en: "Make sure you read your messages and take action when we ask you to. This will help move the application process along." },
  PBS4: { zh: "你的申请处理时间比通常更长。申请量可能逐月变化。请阅读消息并在 IRCC 要求时采取行动。", en: "Your application is taking us longer than usual to process. The volume of applications we receive can vary from one month to the next. Make sure you read your messages and take action when we ask you to." },
  PBS5: { zh: "你的申请处理时间比通常更长。约 20% 的申请更复杂，需要更久处理。请阅读消息并在 IRCC 要求时采取行动。", en: "Your application is taking us longer than usual to process. About 20% of our applications are more complex to process." },
  "01": { zh: "天", en: "day(s)" },
  "02": { zh: "周", en: "week(s)" },
  "03": { zh: "个月", en: "month(s)" },
  "04": { zh: "年", en: "year(s)" },
};

const irccMessageTagMap: Record<string, { zh: string; en: string }> = {
  "Online.RECEIPT": { zh: "在线申请提交收据", en: "Online application receipt" },
  CorrespondenceSent: { zh: "IRCC 已发送信件", en: "IRCC correspondence sent" },
};

const irccHeadlineCodeMap: Record<string, { zh: string; en: string }> = {
  FD2: { zh: "已获批", en: "Approved" },
  FD3: { zh: "已被拒", en: "Refused" },
  FD4: { zh: "已撤回", en: "Withdrawn" },
  FD5: { zh: "已取消", en: "Cancelled" },
  FD6: { zh: "已获批，需要提交护照", en: "Approved, passport submission required" },
  FD7: { zh: "因资料不完整而取消", en: "Cancelled as incomplete" },
  FD8: { zh: "无法撤回", en: "Cannot be withdrawn" },
  FD9: { zh: "已获批，需要提交护照", en: "Approved, passport submission required" },
  FD10: { zh: "已被拒", en: "Refused" },
  FD11: { zh: "已撤回", en: "Withdrawn" },
  FD12: { zh: "无法撤回", en: "Cannot be withdrawn" },
  FD13: { zh: "已找到公民身份记录", en: "Citizenship record found" },
  FD14: { zh: "已找到公民身份记录", en: "Citizenship record found" },
  FD15: { zh: "未找到公民身份记录", en: "Citizenship record not found" },
  FD16: { zh: "未找到公民身份记录", en: "Citizenship record not found" },
  FD17: { zh: "已获批", en: "Approved" },
  FD18: { zh: "已取消", en: "Cancelled" },
  FD20: { zh: "已视为放弃", en: "Abandoned" },
  FD21: { zh: "已视为放弃", en: "Abandoned" },
  FD22: { zh: "不符合转交 IRB 的资格", en: "Ineligible for referral to the IRB" },
  FD23: { zh: "即将提供决定", en: "Decision will be provided shortly" },
};

const irccLatestUpdateLabelMap: Record<string, { zh: string; en: string }> = {
  eligibility: { zh: "资格审查", en: "Review of eligibility" },
  medical: { zh: "体检结果", en: "Review of medical results" },
  additionalDocuments: { zh: "补充文件", en: "Review of additional documents" },
  interviewOrAppointment: { zh: "面试/预约", en: "Interview / appointment" },
  biometricInformation: { zh: "指纹/生物信息", en: "Biometrics" },
  backgroundChecks: { zh: "背景调查", en: "Background check" },
  finalDecision: { zh: "最终决定", en: "Final decision" },
};

const irccChangeLabelMap: Record<string, string> = {
  "总申请状态": "Overall application status",
  "首页申请状态": "Home page status",
  "详情更新时间": "Detail updated time",
  "首页更新时间": "Home updated time",
  "资格审查": "Eligibility review",
  "体检结果": "Medical results",
  "补充文件": "Additional documents",
  "面试/预约": "Interview/appointment",
  "指纹/生物信息": "Biometrics",
  "背景调查": "Background check",
  "最终决定": "Final decision",
  "档案状态": "Profile status",
  "处理时间标题": "Processing time title",
  "处理时间说明": "Processing time message",
  "预计完成日期": "Estimated completion date",
  "预计剩余处理时间": "Estimated remaining processing time",
  "是否超过处理时间": "Processing time exceeded",
  "文件状态": "Document status",
  "申请人信息": "Applicant information",
  "申请消息": "Application messages",
};

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function translateKnownIrccStatusText(value: string): string {
  let output = value;
  const entries = Object.entries(irccStatusCodeMap)
    .filter(([, mapped]) => mapped.zh && mapped.en)
    .sort(([, a], [, b]) => b.zh.length - a.zh.length);
  for (const [code, mapped] of entries) {
    output = output.replace(new RegExp(`${escapeRegExp(mapped.zh)}（${escapeRegExp(code)}）`, "g"), `${mapped.en} (${code})`);
    output = output.replace(new RegExp(escapeRegExp(mapped.zh), "g"), mapped.en);
  }
  return output;
}

function translateIrccChangeSummary(value: string, languageMode: LanguageMode): string {
  const withLocalTimes = formatInlineTimes(value, languageMode);
  if (languageMode === "zh") {
    return withLocalTimes;
  }

  let output = translateKnownIrccStatusText(withLocalTimes)
    .replace(/首次记录 IRCC Portal 快照。/g, "First IRCC Portal snapshot recorded.")
    .replace(/快照指纹变化，但未生成字段级摘要。/g, "Snapshot fingerprint changed, but no field-level summary was generated.")
    .replace(/后台 Ghost update：快照发生变化，但七项状态、申请消息和申请人信息暂无可见变化。/g, "Background ghost update: the snapshot changed, but visible status, messages, and applicant information did not change.")
    .replace(/详情 Ghost update：详情更新时间从 (.*?) 变为 (.*?)；七项状态、申请消息和申请人信息暂无可见变化。/g, "Detail ghost update: detail updated time changed from $1 to $2; visible status, messages, and applicant information did not change.")
    .replace(/首页 Ghost update：首页 submitted applications 更新时间从 (.*?) 变为 (.*?)；详情页暂无可见变化。/g, "Home ghost update: submitted applications updated time changed from $1 to $2; detail page did not show visible changes.")
    .replace(/首页 Ghost update：首页 submitted applications 更新时间从 (.*?) 变为 (.*?)。/g, "Home ghost update: submitted applications updated time changed from $1 to $2.")
    .replace(/Ghost update：首页更新时间从 (.*?) 变为 (.*?)。/g, "Home ghost update: home updated time changed from $1 to $2.")
    .replace(/IRCC Portal 原始时间/g, "IRCC Portal original time")
    .replace(/申请消息新增：/g, "Application message added: ")
    .replace(/申请消息更新：/g, "Application message updated: ")
    .replace(/在线申请提交收据/g, "Online application receipt")
    .replace(/IRCC 已发送信件/g, "IRCC correspondence sent")
    .replace(/未命名消息/g, "Untitled message")
    .replace(/另有 (\d+) 条新增消息/g, "$1 more new message(s)")
    .replace(/另有 (\d+) 条更新消息/g, "$1 more updated message(s)")
    .replace(/申请消息发生变化：(\d+) 条 -> (\d+) 条。/g, "Application messages changed: $1 -> $2 message(s).");

  for (const [zhLabel, enLabel] of Object.entries(irccChangeLabelMap).sort((a, b) => b[0].length - a[0].length)) {
    output = output.replace(new RegExp(escapeRegExp(zhLabel), "g"), enLabel);
  }

  return output
    .replace(/ 发生变化：/g, " changed: ")
    .replace(/(\d+) 条/g, "$1 message(s)")
    .replace(/。/g, ".")
    .replace(/；/g, "; ")
    .replace(/，/g, ", ")
    .replace(/：/g, ": ")
    .replace(/（/g, "(")
    .replace(/）/g, ")");
}

function sanitizeIrccChangeSummaryLine(value: string, languageMode: LanguageMode): string {
  const hasRawApplicantDiff = /(\[\s*\{|\{\s*['"]?(fullName|uci|appNumber|biometricNumber)['"]?\s*:)/.test(value)
    && /(-&gt;|->)/.test(value);
  if (hasRawApplicantDiff) {
    return languageMode === "zh" ? "申请人信息已更新。" : "Applicant information updated.";
  }
  return value
    .replace(/，时间：(?=\d{2}\/\d{2}\/\d{4}\s+\d{2}:\d{2}:\d{2})/g, languageMode === "zh" ? "，IRCC Portal 原始时间：" : ", IRCC Portal original time: ")
    .trim();
}

function formatIrccChangeSummaryLines(value: string, languageMode: LanguageMode): string[] {
  return value
    .split(/\n+/)
    .map((line) => sanitizeIrccChangeSummaryLine(translateIrccChangeSummary(line, languageMode), languageMode))
    .filter(Boolean);
}

function stripHtmlText(value: unknown): string {
  const raw = String(value ?? "");
  return raw
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

function formatIrccCode(value: string, languageMode: LanguageMode): string {
  if (!value) {
    return "-";
  }
  const mapped = irccStatusCodeMap[value];
  if (!mapped) {
    return `${languageMode === "zh" ? "未知状态码" : "Unknown status code"}：${value}`;
  }
  if (!mapped[languageMode]) {
    return "-";
  }
  return languageMode === "zh" ? `${mapped[languageMode]}（${value}）` : `${mapped[languageMode]} (${value})`;
}

function formatIrccHeadline(overview: IrccStatusOverview | null | undefined, languageMode: LanguageMode): string {
  if (!overview?.headlineCode) {
    return languageMode === "zh" ? "等待首次查询" : "Waiting for first query";
  }
  const text = irccHeadlineCodeMap[overview.headlineCode]?.[languageMode]
    || irccStatusCodeMap[overview.headlineCode]?.[languageMode]
    || (languageMode === "zh" ? `未知状态码：${overview.headlineCode}` : `Unknown status code: ${overview.headlineCode}`);
  return languageMode === "zh" ? `${text}（${overview.headlineCode}）` : `${text} (${overview.headlineCode})`;
}

function formatIrccCompactHeadline(overview: IrccStatusOverview | null | undefined, languageMode: LanguageMode): string {
  if (!overview?.headlineCode) {
    return languageMode === "zh" ? "等待首次查询" : "Waiting for first query";
  }
  return irccHeadlineCodeMap[overview.headlineCode]?.[languageMode]
    || irccStatusCodeMap[overview.headlineCode]?.[languageMode]
    || (languageMode === "zh" ? `未知状态码：${overview.headlineCode}` : `Unknown status code: ${overview.headlineCode}`);
}

function getIrccToneBadgeClass(tone: IrccStatusTone | undefined, extraClass = ""): string {
  const semanticClass = tone === "approved" ? "success" : tone === "negative" ? "error" : "";
  return ["status-badge", "ircc-headline-badge", semanticClass, extraClass].filter(Boolean).join(" ");
}

function formatIrccLatestUpdateTime(value: string | null, languageMode: LanguageMode): string {
  const text = String(value || "").trim();
  const matched = text.match(/^(\d{2})\/(\d{2})\/(\d{4})(?:\s+(\d{2}):(\d{2}):(\d{2}))?$/);
  if (!matched) {
    return text || "-";
  }
  const [, month, day, year, hour, minute, second] = matched;
  const datePart = languageMode === "zh"
    ? `${Number(year)}/${Number(month)}/${Number(day)}`
    : `${Number(month)}/${Number(day)}/${year}`;
  return hour ? `${datePart} ${hour}:${minute}:${second}` : datePart;
}

function formatIrccLatestUpdateLabel(field: string, fallback: string, languageMode: LanguageMode): string {
  return irccLatestUpdateLabelMap[field]?.[languageMode] || fallback;
}

function formatIrccBoolean(value: unknown, languageMode: LanguageMode): string {
  if (typeof value !== "boolean") {
    return "-";
  }
  return value ? (languageMode === "zh" ? "是" : "Yes") : (languageMode === "zh" ? "否" : "No");
}

function formatIrccPlainValue(value: unknown, languageMode: LanguageMode): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "boolean") {
    return formatIrccBoolean(value, languageMode);
  }
  if (typeof value === "string" && irccStatusCodeMap[value]) {
    return formatIrccCode(value, languageMode);
  }
  return String(value);
}

function formatIrccRemainingTime(appStatus: Record<string, unknown>, languageMode: LanguageMode): string {
  const value = appStatus.estimatedRemainingProcessingTime;
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  const unit = typeof appStatus.estimatedRemainingProcessingTimeUnitOfMeasure === "string"
    ? formatIrccCode(appStatus.estimatedRemainingProcessingTimeUnitOfMeasure, languageMode)
    : "";
  return `${value}${unit && unit !== "-" ? ` ${unit}` : ""}`;
}

function hasIrccValue(value: unknown): boolean {
  if (value === null || value === undefined || value === "") {
    return false;
  }
  if (typeof value === "string" && ["PBT0", "PBS0"].includes(value)) {
    return false;
  }
  if (typeof value === "number" && value === 0) {
    return false;
  }
  return true;
}

function formatIrccMessageTag(value: unknown, languageMode: LanguageMode): string {
  const tag = String(value ?? "");
  if (!tag) {
    return languageMode === "zh" ? "申请消息" : "Message";
  }
  return irccMessageTagMap[tag]?.[languageMode] ?? tag;
}

function readIrccStatus(status: unknown, languageMode: LanguageMode): string {
  if (typeof status === "string") {
    return formatIrccCode(status, languageMode);
  }
  if (status && typeof status === "object" && "status" in status) {
    const value = String((status as { status?: unknown }).status ?? "");
    const timeStamp = String((status as { timeStamp?: unknown }).timeStamp ?? "");
    const timeLabel = languageMode === "zh" ? "IRCC Portal 原始时间" : "IRCC Portal original time";
    return `${formatIrccCode(value, languageMode)}${timeStamp ? ` · ${timeLabel}: ${timeStamp}` : ""}`;
  }
  return status == null || status === "" ? "-" : JSON.stringify(status);
}

function getIrccApplicant(snapshot: IrccSnapshot | null): Record<string, unknown> {
  const appStatus = snapshot?.appStatus;
  const list = appStatus?.listOfApplicants;
  return Array.isArray(list) && list[0] && typeof list[0] === "object" ? list[0] as Record<string, unknown> : {};
}

function sortIrccMessagesNewestFirst(messages: Array<Record<string, unknown>>): Array<Record<string, unknown>> {
  return [...messages].sort((left, right) => {
    const leftTime = parsePortableTime(String(left.updatedDttm || left.createdDttm || ""))?.getTime() ?? 0;
    const rightTime = parsePortableTime(String(right.updatedDttm || right.createdDttm || ""))?.getTime() ?? 0;
    return rightTime - leftTime;
  });
}

function KoreaCaseDetail(props: {
  targetCase: KoreaCase;
  history: KoreaHistoryItem[];
  runQuery: (caseId: number) => Promise<void>;
  sendTestEmail: (caseId: number) => Promise<void>;
  removeCase: (caseId: number) => Promise<void>;
  toggleEmailPush: (targetCase: KoreaCase) => Promise<void>;
  stopAutomaticQuery: (targetCase: KoreaCase) => Promise<void>;
  isBusy: boolean;
  t: (key: TranslationKey) => string;
  languageMode: LanguageMode;
}) {
  const sortedHistory = useMemo(() => {
    return [...props.history].sort((left, right) => {
      const leftTime = parsePortableTime(left.fetchedAt)?.getTime() ?? 0;
      const rightTime = parsePortableTime(right.fetchedAt)?.getTime() ?? 0;
      return rightTime - leftTime || right.id - left.id;
    });
  }, [props.history]);

  return (
    <>
      <section className="panel">
        <div className="panel-title">
          <div>
            <h2 className="headline">{props.targetCase.displayName}</h2>
            <p className="form-intro compact">{props.t("countryKorea")} · {props.t("koreaVisaTitle")} · {props.t("irccAlphaLabel")}</p>
          </div>
          <div className="row-actions">
            <button className="button secondary" onClick={() => props.runQuery(props.targetCase.id)} disabled={props.isBusy}>
              <Activity size={16} /> {props.t("fastQuery")}
            </button>
            <button className="button secondary" onClick={() => props.sendTestEmail(props.targetCase.id)} disabled={props.isBusy || props.history.length === 0}>
              <Mail size={16} /> {props.t("koreaTestEmail")}
            </button>
            <button className="icon-button danger" onClick={() => { if (confirm(props.t("confirmDelete"))) void props.removeCase(props.targetCase.id); }}>
              <Trash2 size={16} />
            </button>
          </div>
        </div>
        <div className="stack">
          {props.targetCase.lastErrorMessage && (
            <div className="notice">
              <strong>{props.t("koreaLastError")}：</strong>{props.targetCase.lastErrorMessage}
            </div>
          )}
          <div className="two-col metric-grid">
            <Metric icon={<FileText size={14} />} label={`${props.t("passport")} / ${props.t("koreaEnglishName")}`} value={`${props.targetCase.passportNumber} / ${props.targetCase.englishName}`} />
            <Metric icon={<Clock size={14} />} label={props.t("koreaBirthDate")} value={props.targetCase.birthDate} />
          </div>
          <div className="two-col metric-grid">
            <Metric icon={<FileText size={14} />} label={props.t("koreaApplicationNo")} value={props.targetCase.lastApplicationNo || "-"} />
            <Metric icon={<Clock size={14} />} label={props.t("koreaApplicationDate")} value={props.targetCase.lastApplicationDate || "-"} />
          </div>
          <div className="two-col metric-grid">
            <Metric icon={<MapPin size={14} />} label={props.t("koreaEntryPurpose")} value={props.targetCase.lastEntryPurpose || "-"} />
            <Metric icon={<Activity size={14} />} label={props.t("status")}>
              <span className={getStatusBadgeClass(props.targetCase.lastStatus, "metric-status")}>
                {props.targetCase.lastStatus || props.t("noStatus")}
              </span>
            </Metric>
          </div>
          <div className="two-col metric-grid">
            <Metric icon={<Clock size={14} />} label={props.t("lastCheckedAt")} value={formatTime(props.targetCase.lastCheckedAt, props.languageMode)} />
            <Metric icon={<Activity size={14} />} label={props.t("lastCheckMode")} value={formatTriggerType(props.targetCase.lastTriggerType, props.t)} />
          </div>
          <div className="two-col metric-grid">
            <Metric icon={<Clock size={14} />} label={props.t("nextCheckAt")} value={formatTime(props.targetCase.nextCheckAt, props.languageMode)} />
            <Metric icon={<Bell size={14} />} label={props.t("emailPushSetting")} value={props.targetCase.emailNotificationsEnabled ? props.t("emailPushOn") : props.t("emailPushOff")} />
          </div>
          <div className="settings-row">
            <label className="checkbox">
              <input
                type="checkbox"
                checked={props.targetCase.emailNotificationsEnabled}
                onChange={() => props.toggleEmailPush(props.targetCase)}
                disabled={props.isBusy}
              />
              <span className="body-sm">{props.t("emailPushSetting")}</span>
            </label>
            <button className="button secondary" onClick={() => props.stopAutomaticQuery(props.targetCase)} disabled={props.isBusy || !props.targetCase.isEnabled}>
              {props.t("stopAutomaticQuery")}
            </button>
          </div>
        </div>
      </section>
      <section className="panel">
        <div className="panel-title">
          <h2 className="subhead">{props.t("statusHistory")}</h2>
          <History size={18} />
        </div>
        <div className="timeline">
          {sortedHistory.map((item) => {
            const detailLines = [
              item.applicationNo ? `${props.t("koreaApplicationNo")}: ${item.applicationNo}` : "",
              item.applicationDate ? `${props.t("koreaApplicationDate")}: ${item.applicationDate}` : "",
              item.entryPurpose ? `${props.t("koreaEntryPurpose")}: ${item.entryPurpose}` : "",
            ].filter(Boolean);
            const status = item.status || props.t("noStatus");

            return (
              <div className="timeline-item" key={item.id}>
                <div className="korea-history-header">
                  <div className="korea-history-status-group">
                    <span className="korea-history-status-label">{props.t("koreaProgressStatus")}</span>
                    <span className={getStatusBadgeClass(status, "korea-history-status")}>{status}</span>
                  </div>
                  <span className="timeline-time">{formatTime(item.fetchedAt, props.languageMode)}</span>
                </div>
                {detailLines.length > 0 && (
                  <div className="timeline-desc-list">
                    {detailLines.map((line) => (
                      <div className="timeline-desc timeline-desc-line" key={line}>{line}</div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          {sortedHistory.length === 0 && (
            <div className="empty-state">
              <div className="empty-state-icon"><History size={24} /></div>
              <p>{props.t("koreaNoHistory")}</p>
            </div>
          )}
        </div>
      </section>
    </>
  );
}

function IrccCaseDetail(props: {
  targetCase: IrccCase;
  history: IrccHistoryItem[];
  runQuery: (caseId: number) => Promise<void>;
  sendTestEmail: (caseId: number) => Promise<void>;
  removeCase: (caseId: number) => Promise<void>;
  toggleEmailPush: (targetCase: IrccCase) => Promise<void>;
  toggleAutomaticQuery: (targetCase: IrccCase) => Promise<void>;
  isBusy: boolean;
  t: (key: TranslationKey) => string;
  languageMode: LanguageMode;
}) {
  const snapshot = props.targetCase.latestSnapshot;
  const appStatus = snapshot?.appStatus ?? {};
  const applicationInfo = snapshot?.applicationInfo ?? {};
  const statusOverview = props.targetCase.statusOverview;
  const messages = Array.isArray(snapshot?.messages) ? snapshot.messages : [];
  const sortedMessages = sortIrccMessagesNewestFirst(messages);
  const documentStatus = Array.isArray(appStatus.documentStatus) ? appStatus.documentStatus : [];
  const applicant = getIrccApplicant(snapshot);
  const hasProcessingTimeDetails = Boolean(appStatus.processingTimeAvailable)
    || hasIrccValue(appStatus.processingTimeBarTitle)
    || hasIrccValue(appStatus.processingTimeBarMessage)
    || hasIrccValue(appStatus.estimatedCompletionDate)
    || hasIrccValue(appStatus.estimatedRemainingProcessingTime)
    || appStatus.processingTimeExceeded === true;
  const statusLabels = props.languageMode === "zh"
    ? {
        eligibility: "资格审查",
        medical: "体检结果",
        additionalDocuments: "补充文件",
        interview: "面试",
        biometrics: "指纹/生物信息",
        backgroundCheck: "背景调查",
        finalDecision: "最终决定",
        homeStatus: "首页申请状态",
        homeGhostUpdate: "首页更新时间",
        principalApplicant: "主申请人",
        applicationNumber: "Application number",
        dateReceived: "接收日期",
        biometricsNumber: "指纹编号",
        biometricsExpiry: "指纹有效期",
        processingTitle: "处理时间标题",
        processingMessage: "处理时间说明",
        estimatedCompletionDate: "预计完成日期",
        remainingProcessingTime: "预计剩余处理时间",
        processingTimeAvailable: "处理时间可用",
        processingTimeExceeded: "已超过处理时间",
        documentStatus: "文件状态",
      }
    : {
        eligibility: "Review of eligibility",
        medical: "Review of medical results",
        additionalDocuments: "Review of additional documents",
        interview: "Interview",
        biometrics: "Biometrics",
        backgroundCheck: "Background check",
        finalDecision: "Final decision",
        homeStatus: "Home page status",
        homeGhostUpdate: "Home updated time",
        principalApplicant: "Principal applicant",
        applicationNumber: "Application number",
        dateReceived: "Date received",
        biometricsNumber: "Biometrics number",
        biometricsExpiry: "Biometrics expiry",
        processingTitle: "Processing time title",
        processingMessage: "Processing time message",
        estimatedCompletionDate: "Estimated completion date",
        remainingProcessingTime: "Estimated remaining processing time",
        processingTimeAvailable: "Processing time available",
        processingTimeExceeded: "Processing time exceeded",
        documentStatus: "Document status",
      };
  return (
    <div className="ircc-detail-stack">
      <section className="panel">
        <div className="panel-title">
          <div>
            <h2 className="headline">{props.targetCase.displayName}</h2>
            <p className="form-intro compact">{props.t("countryCanada")} · {props.t("irccPortalTitle")} · {props.t("irccAlphaLabel")}</p>
          </div>
          <div className="row-actions">
            <button className="button secondary" onClick={() => props.runQuery(props.targetCase.id)} disabled={props.isBusy}>
              <Activity size={16} /> {props.t("fastQuery")}
            </button>
            <button className="button secondary" onClick={() => props.sendTestEmail(props.targetCase.id)} disabled={props.isBusy || props.history.length === 0}>
              <Mail size={16} /> {props.t("irccTestEmail")}
            </button>
            <button className="icon-button danger" onClick={() => { if (confirm(props.t("confirmDelete"))) void props.removeCase(props.targetCase.id); }}>
              <Trash2 size={16} />
            </button>
          </div>
        </div>
        <div className="stack">
          <div className="notice">{props.t("irccPortalIntro")}</div>
          {props.targetCase.lastErrorMessage && (
            <div className="notice">
              <strong>{props.t("irccLastError")}：</strong>{props.targetCase.lastErrorMessage}
            </div>
          )}
          <div className="two-col metric-grid ircc-metric-grid">
            <Metric icon={<FileText size={14} />} label={props.t("irccApplicationNumber")} value={props.targetCase.applicationNumber || "-"} />
            <Metric icon={<FileText size={14} />} label={props.t("irccAppId")} value={props.targetCase.appId} />
          </div>
          <div className="two-col metric-grid ircc-metric-grid">
            <Metric icon={<User size={14} />} label={props.t("irccPrincipalApplicant")} value={props.targetCase.principalApplicant || String(applicant.fullName || "-")} />
            <Metric icon={<Mail size={14} />} label={props.t("irccPortalEmail")} value={props.targetCase.portalEmailMasked} />
          </div>
          <div className="two-col metric-grid ircc-metric-grid">
            <Metric icon={<Mail size={14} />} label={props.t("notifyEmail")} value={props.targetCase.receiveEmail} />
            <Metric icon={<Activity size={14} />} label={props.t("lastCheckMode")} value={formatTriggerType(props.targetCase.lastTriggerType, props.t)} />
          </div>
          <div className="two-col metric-grid ircc-metric-grid">
            <Metric icon={<Clock size={14} />} label={props.t("lastCheckedAt")} value={formatTime(props.targetCase.lastCheckedAt, props.languageMode)} />
            <Metric icon={<Clock size={14} />} label={props.t("nextCheckAt")} value={formatTime(props.targetCase.nextCheckAt, props.languageMode)} />
          </div>
          <div className="settings-row">
            <label className="checkbox">
              <input
                type="checkbox"
                checked={props.targetCase.emailNotificationsEnabled}
                onChange={() => props.toggleEmailPush(props.targetCase)}
                disabled={props.isBusy}
              />
              <span className="body-sm">{props.t("emailPushSetting")}</span>
            </label>
            <button className="button secondary" onClick={() => props.toggleAutomaticQuery(props.targetCase)} disabled={props.isBusy}>
              {props.targetCase.isEnabled ? props.t("stopAutomaticQuery") : props.t("startAutomaticQuery")}
            </button>
          </div>
        </div>
      </section>

      <section className="panel ircc-section">
        <div className="panel-title">
          <h2 className="subhead">{props.t("irccApplicantInfo")}</h2>
          <UserRound size={18} />
        </div>
        <div className="two-col metric-grid ircc-metric-grid">
          <Metric label={statusLabels.principalApplicant} value={String(applicant.fullName || props.targetCase.principalApplicant || "-")} />
          <Metric label="UCI" value={String(applicant.uci || "-")} />
        </div>
        <div className="two-col metric-grid ircc-metric-grid">
          <Metric label={statusLabels.applicationNumber} value={String(applicant.appNumber || props.targetCase.applicationNumber || "-")} />
          <Metric label={statusLabels.dateReceived} value={String(applicant.receivedDate || "-")} />
        </div>
        <div className="two-col metric-grid ircc-metric-grid">
          <Metric label={statusLabels.biometricsNumber} value={String(applicant.biometricNumber || "-")} />
          <Metric label={statusLabels.biometricsExpiry} value={String(applicant.biometricExpiryDate || "-")} />
        </div>
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2 className="subhead">{props.t("irccApplicationStatus")}</h2>
          <span className={getIrccToneBadgeClass(statusOverview?.tone)}>
            {statusOverview ? formatIrccHeadline(statusOverview, props.languageMode) : props.t("noStatus")}
          </span>
        </div>
        {statusOverview && (
          <div className={`ircc-status-overview ${statusOverview.tone}`}>
            <div className="ircc-overview-group">
              <span className="ircc-overview-label">{props.t("irccStatusOverview")}</span>
              <strong className="ircc-overview-headline">{formatIrccHeadline(statusOverview, props.languageMode)}</strong>
            </div>
            <div className="ircc-overview-group">
              <span className="ircc-overview-label">{props.t("irccOverallStatus")}</span>
              <p className="ircc-overview-text">{formatIrccCode(statusOverview.overallCode, props.languageMode)}</p>
            </div>
            {statusOverview.latestUpdate && (
              <div className="ircc-overview-group latest">
                <span className="ircc-overview-label">{props.t("irccLatestUpdate")}</span>
                <p className="ircc-overview-text">
                  <strong>
                    {formatIrccLatestUpdateLabel(statusOverview.latestUpdate.field, statusOverview.latestUpdate.label, props.languageMode)}
                    {" - "}
                    {formatIrccLatestUpdateTime(statusOverview.latestUpdate.timeStamp, props.languageMode)}
                  </strong>
                </p>
                <p className="ircc-overview-text">{formatIrccCode(statusOverview.latestUpdate.code, props.languageMode)}</p>
              </div>
            )}
          </div>
        )}
        <div className="two-col metric-grid ircc-metric-grid">
          <Metric label={statusLabels.eligibility} value={readIrccStatus(appStatus.eligibility, props.languageMode)} />
          <Metric label={statusLabels.medical} value={readIrccStatus(appStatus.medical, props.languageMode)} />
        </div>
        <div className="two-col metric-grid ircc-metric-grid">
          <Metric label={statusLabels.additionalDocuments} value={readIrccStatus(appStatus.additionalDocuments, props.languageMode)} />
          <Metric label={statusLabels.interview} value={readIrccStatus(appStatus.interviewOrAppointment, props.languageMode)} />
        </div>
        <div className="two-col metric-grid ircc-metric-grid">
          <Metric label={statusLabels.biometrics} value={readIrccStatus(appStatus.biometricInformation, props.languageMode)} />
          <Metric label={statusLabels.backgroundCheck} value={readIrccStatus(appStatus.backgroundChecks, props.languageMode)} />
        </div>
        <div className="two-col metric-grid ircc-metric-grid">
          <Metric label={statusLabels.finalDecision} value={readIrccStatus(appStatus.finalDecision, props.languageMode)} />
          <Metric label={statusLabels.homeStatus} value={formatIrccPlainValue(applicationInfo.appStatus, props.languageMode)} />
        </div>
        <div className="two-col metric-grid ircc-metric-grid">
          <Metric label={statusLabels.homeGhostUpdate} value={applicationInfo.updatedTimestamp || applicationInfo.updatedDate ? formatTime(String(applicationInfo.updatedTimestamp || applicationInfo.updatedDate), props.languageMode) : "-"} />
        </div>
        <p className="form-intro compact ircc-ghost-note">{props.t("irccGhostUpdate")}</p>
      </section>

      {hasProcessingTimeDetails && (
        <section className="panel">
          <div className="panel-title">
            <h2 className="subhead">{statusLabels.processingTitle}</h2>
            <span className="status-badge">{formatIrccBoolean(appStatus.processingTimeAvailable, props.languageMode)}</span>
          </div>
          <div className="two-col metric-grid ircc-metric-grid">
            {hasIrccValue(appStatus.processingTimeBarTitle) && <Metric label={statusLabels.processingTitle} value={formatIrccPlainValue(appStatus.processingTimeBarTitle, props.languageMode)} />}
            {hasIrccValue(appStatus.processingTimeBarMessage) && <Metric label={statusLabels.processingMessage} value={formatIrccPlainValue(appStatus.processingTimeBarMessage, props.languageMode)} />}
          </div>
          <div className="two-col metric-grid ircc-metric-grid">
            {hasIrccValue(appStatus.estimatedCompletionDate) && <Metric label={statusLabels.estimatedCompletionDate} value={formatIrccPlainValue(appStatus.estimatedCompletionDate, props.languageMode)} />}
            {hasIrccValue(appStatus.estimatedRemainingProcessingTime) && <Metric label={statusLabels.remainingProcessingTime} value={formatIrccRemainingTime(appStatus, props.languageMode)} />}
          </div>
          {appStatus.processingTimeExceeded === true && (
            <div className="two-col metric-grid ircc-metric-grid">
              <Metric label={statusLabels.processingTimeExceeded} value={formatIrccBoolean(appStatus.processingTimeExceeded, props.languageMode)} />
            </div>
          )}
        </section>
      )}

      {documentStatus.length > 0 && (
        <section className="panel">
          <div className="panel-title">
            <h2 className="subhead">{statusLabels.documentStatus}</h2>
            <span className="status-badge">{documentStatus.length}</span>
          </div>
          <div className="timeline">
            {documentStatus.map((item, index) => (
              <div key={index} className="timeline-item">
                <div className="timeline-desc">{JSON.stringify(item)}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="panel">
        <div className="panel-title">
          <h2 className="subhead">{props.t("irccMessages")}</h2>
          <Mail size={18} />
        </div>
        <div className="timeline">
          {sortedMessages.map((message, index) => {
            const details = typeof message.messageDetails === "object" && message.messageDetails ? message.messageDetails as Record<string, unknown> : {};
            const attachment = typeof details.attachment === "object" && details.attachment ? details.attachment as Record<string, unknown> : {};
            const subject = stripHtmlText(details.subject) || stripHtmlText(attachment.attachmentFileName) || "-";
            return (
              <div key={String(message.messageId ?? index)} className="timeline-item">
                <div className="timeline-header">
                  <span className="timeline-time">{formatTime(String(message.updatedDttm || message.createdDttm || ""), props.languageMode)}</span>
                  <span className="status-badge">{formatIrccMessageTag(details.messageTag || details.messageType, props.languageMode)}</span>
                </div>
                <div className="timeline-desc">{subject}</div>
              </div>
            );
          })}
          {sortedMessages.length === 0 && (
            <div className="empty-state">
              <div className="empty-state-icon"><Mail size={24} /></div>
              <p>{props.t("irccNoHistory")}</p>
            </div>
          )}
        </div>
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2 className="subhead">{props.t("statusHistory")}</h2>
          <History size={18} />
        </div>
        <div className="timeline">
          {props.history.map((record) => (
            <div key={record.id} className="timeline-item">
              <div className="timeline-header">
                <span className="timeline-time">{formatTime(record.fetchedAt, props.languageMode)}</span>
                <span className={`status-badge ${record.notificationSent ? "success" : ""}`}>{record.notificationSent ? props.t("notificationSent") : props.t("notificationNotSent")}</span>
              </div>
              <div className="timeline-desc-list">
                {formatIrccChangeSummaryLines(record.changeSummary, props.languageMode).map((line, index) => (
                  <div className="timeline-desc timeline-desc-line" key={index}>{line}</div>
                ))}
              </div>
            </div>
          ))}
          {props.history.length === 0 && (
            <div className="empty-state">
              <div className="empty-state-icon"><History size={24} /></div>
              <p>{props.t("irccNoHistory")}</p>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function TermsDialog(props: { t: (key: TranslationKey) => string; languageMode: LanguageMode; onClose: () => void }) {
  const sections = legalTerms[props.languageMode];
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={props.onClose}>
      <section
        className="modal-panel terms-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="terms-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <h2 id="terms-dialog-title" className="headline">{props.t("termsTitle")}</h2>
            <p className="form-intro compact">{props.t("termsVersion")}: {USER_TERMS_VERSION_LABEL}</p>
          </div>
          <button type="button" className="icon-button" onClick={props.onClose} aria-label={props.t("closeTerms")}>
            <X size={18} />
          </button>
        </div>
        <div className="terms-content">
          {sections.map((section) => (
            <section key={section.title} className="terms-section">
              <h3>{section.title}</h3>
              {section.body.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </section>
          ))}
        </div>
        <div className="modal-actions">
          <button type="button" className="button primary" onClick={props.onClose}>
            {props.t("closeTerms")}
          </button>
        </div>
      </section>
    </div>
  );
}

function SiteFooter(props: { t: (key: TranslationKey) => string }) {
  return (
    <footer className="site-footer">
      <span>{props.t("nonprofitNotice")}</span>
      <span>{props.t("contactEmail")}</span>
      <a href="https://github.com/Mike-Zhuang/CEACStatusBot_Web" target="_blank" rel="noreferrer">
        {props.t("sourceCode")}
      </a>
      {icpRecordNumber && (
        <a href="https://beian.miit.gov.cn/" target="_blank" rel="noreferrer">
          {icpRecordNumber}
        </a>
      )}
    </footer>
  );
}

function ThemeButton(props: { themeMode: ThemeMode; setThemeMode: (mode: ThemeMode) => void; t: (key: TranslationKey) => string }) {
  const nextTitle = props.themeMode === "dark" ? props.t("themeToLight") : props.t("themeToDark");
  return (
    <button
      className="button tertiary theme-toggle"
      onClick={() => props.setThemeMode(props.themeMode === "dark" ? "light" : "dark")}
      title={nextTitle}
      style={{ padding: "8px" }}
    >
      {props.themeMode === "dark" ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}

function LanguageButton(props: { languageMode: LanguageMode; setLanguageMode: (mode: LanguageMode) => void }) {
  return (
    <button
      className="button tertiary language-toggle"
      onClick={() => props.setLanguageMode(props.languageMode === "zh" ? "en" : "zh")}
      title={props.languageMode === "zh" ? "Switch to English" : "切换到中文"}
    >
      {props.languageMode === "zh" ? "EN" : "中"}
    </button>
  );
}

function Metric(props: { label: string; value?: string; children?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="metric hover-card">
      <div className="metric-header">
        {props.icon && <div className="metric-icon">{props.icon}</div>}
        <div className="caption">{props.label}</div>
      </div>
      <div className="body-sm">{props.children ?? props.value}</div>
    </div>
  );
}

function summarizePassportSlotResult(result: PassportSlotMonitor["lastResult"], languageMode: LanguageMode): string {
  if (result?.slotStatus === "not_eligible") {
    return result.statusMessage || (languageMode === "zh" ? "暂不具备护照预约资格" : "Not eligible for passport appointment yet");
  }
  if (result?.slotStatus === "no_slot") {
    return result.statusMessage || (languageMode === "zh" ? "已可预约但暂无 slot" : "Eligible, but no available slot");
  }
  const slots = Array.isArray(result?.availableSlots)
    ? result.availableSlots
    : Array.isArray(result?.availableDates)
      ? result.availableDates
      : [];
  if (!slots.length) {
    return languageMode === "zh" ? "暂无可预约时间" : "No available slot";
  }
  return slots.slice(0, 3).map((slot) => {
    if (slot && typeof slot === "object") {
      const record = slot as Record<string, unknown>;
      const parts = ["date", "time", "datetime", "dateTime", "startTime", "city", "location"]
        .map((key) => record[key] ? `${key}: ${String(record[key])}` : "")
        .filter(Boolean);
      return parts.join("; ") || JSON.stringify(record);
    }
    return String(slot);
  }).join(" | ");
}

function formatPassportSlotStatus(result: PassportSlotMonitor["lastResult"], t: (key: TranslationKey) => string): string {
  if (result?.slotStatus === "not_eligible") {
    return t("passportSlotNotEligible");
  }
  if (result?.slotStatus === "no_slot") {
    return t("passportSlotNoSlot");
  }
  if (result?.slotStatus === "has_slot") {
    return t("passportSlotStatusHasSlot");
  }
  return result?.statusMessage || t("waitFirstQuery");
}

function hasSeenPassportSlot(monitor: PassportSlotMonitor | null, history: PassportSlotHistoryItem[]): boolean {
  if (monitor?.lastResult?.slotStatus === "has_slot" || (monitor?.lastSlotFingerprint ?? "").startsWith("state:has_slot:")) {
    return true;
  }
  return history.some((item) => {
    const slotStatus = typeof item.rawPayload?.slotStatus === "string" ? item.rawPayload.slotStatus : "";
    return slotStatus === "has_slot" || item.slotFingerprint.startsWith("state:has_slot:");
  });
}

function PassportSlotMonitorPanel(props: {
  selectedCase: CeacCase;
  monitor: PassportSlotMonitor | null;
  history: PassportSlotHistoryItem[];
  identifier: string;
  setIdentifier: (value: string) => void;
  saveMonitor: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  toggleMonitor: (targetCase: CeacCase, targetMonitor: PassportSlotMonitor) => Promise<void>;
  toggleEmailNotifications: (targetCase: CeacCase, targetMonitor: PassportSlotMonitor) => Promise<void>;
  confirmBooked: (targetCase: CeacCase, targetMonitor: PassportSlotMonitor) => Promise<void>;
  runQuery: (caseId: number) => Promise<void>;
  sendTestEmail: (caseId: number) => Promise<void>;
  isBusy: boolean;
  t: (key: TranslationKey) => string;
  languageMode: LanguageMode;
}) {
  const isReadyStatus = isPassportSlotReadyStatus(props.selectedCase.lastStatus);
  const shouldShowBookedStop = Boolean(props.monitor?.isEnabled && hasSeenPassportSlot(props.monitor, props.history));
  return (
    <section className={`panel passport-slot-panel ${isReadyStatus ? "ready" : ""}`}>
      <div className="panel-title">
        <div>
          <h2 className="subhead inline-title">
            {props.t("passportSlotMonitor")}
          </h2>
          <p className="form-intro">
            {isReadyStatus ? props.t("passportSlotIntro") : props.t("passportSlotEarlyHint")}
          </p>
          <p className="form-intro compact">{props.t("passportSlotDetectionOnly")}</p>
        </div>
        {props.monitor && (
          <span className={`status-badge ${props.monitor.isEnabled ? "success" : ""}`}>
            {props.monitor.isEnabled ? props.t("autoMonitor") : props.t("passportSlotDisabled")}
          </span>
        )}
      </div>

      <form className="inline-monitor-form" onSubmit={props.saveMonitor}>
        <label>
          {props.t("passportSlotIdentifier")}
          <input
            value={props.identifier}
            onChange={(event) => props.setIdentifier(event.target.value.trim().toUpperCase())}
            placeholder={props.t("passportSlotIdentifierPlaceholder")}
            required
          />
        </label>
        <button className="button primary" disabled={props.isBusy}>
          {props.t("passportSlotSave")}
        </button>
      </form>

      {props.monitor ? (
        <div className="stack">
          <div className="two-col metric-grid">
            <Metric label={props.t("passportSlotConfigured")} value={props.monitor.identifierMasked} />
            <Metric label={props.t("passportSlotCurrentStatus")} value={formatPassportSlotStatus(props.monitor.lastResult, props.t)} />
          </div>
          <div className="two-col metric-grid">
            <Metric label={props.t("passportSlotLastCount")} value={String(props.monitor.lastSlotCount)} />
            <Metric label={props.t("lastCheckedAt")} value={formatTime(props.monitor.lastCheckedAt, props.languageMode)} />
          </div>
          <div className="two-col metric-grid">
            <Metric label={props.t("nextCheckAt")} value={formatTime(props.monitor.nextCheckAt, props.languageMode)} />
          </div>
          <Metric label={props.t("changeContent")} value={summarizePassportSlotResult(props.monitor.lastResult, props.languageMode)} />
          {props.monitor.lastErrorMessage && (
            <Metric label={props.t("passportSlotLastError")} value={props.monitor.lastErrorMessage} />
          )}
          <div className="settings-row">
            <label className="checkbox">
              <input
                type="checkbox"
                checked={props.monitor.isEnabled}
                onChange={() => props.toggleMonitor(props.selectedCase, props.monitor!)}
                disabled={props.isBusy}
              />
              <span className="body-sm">{props.t("autoMonitor")}</span>
            </label>
            <span className={`status-badge ${props.monitor.isEnabled ? "success" : ""}`}>
              {props.monitor.isEnabled ? props.t("passportSlotEnabled") : props.t("passportSlotDisabled")}
            </span>
          </div>
          <div className="settings-row">
            <label className="checkbox">
              <input
                type="checkbox"
                checked={props.monitor.emailNotificationsEnabled}
                onChange={() => props.toggleEmailNotifications(props.selectedCase, props.monitor!)}
                disabled={props.isBusy}
              />
              <span className="body-sm">{props.t("emailPushSetting")}</span>
            </label>
            <span className={`status-badge ${props.monitor.emailNotificationsEnabled ? "success" : ""}`}>
              {props.monitor.emailNotificationsEnabled ? props.t("emailPushOn") : props.t("emailPushOff")}
            </span>
          </div>
          <div className="row-actions">
            <button
              type="button"
              className="button secondary"
              onClick={() => props.runQuery(props.selectedCase.id)}
              disabled={props.isBusy}
            >
              <Activity size={16} /> {props.t("passportSlotManualQuery")}
            </button>
            <button
              type="button"
              className="button secondary"
              onClick={() => props.sendTestEmail(props.selectedCase.id)}
              disabled={props.isBusy}
            >
              <Mail size={16} /> {props.t("passportSlotTestEmail")}
            </button>
            {shouldShowBookedStop && (
              <button
                type="button"
                className="button primary"
                onClick={() => props.confirmBooked(props.selectedCase, props.monitor!)}
                disabled={props.isBusy}
              >
                <CheckCircle2 size={16} /> {props.t("passportSlotBookedStop")}
              </button>
            )}
          </div>
          <div className="mini-history">
            <div className="caption">{props.t("passportSlotHistory")}</div>
            {props.history.slice(0, 3).map((item) => (
              <div key={item.id} className="mini-history-row">
                <span>{formatTime(item.fetchedAt, props.languageMode)}</span>
                <span>{formatPassportSlotStatus(item.rawPayload as PassportSlotMonitor["lastResult"], props.t)} / {item.slotCount} slot</span>
                <span>{item.notificationSent ? props.t("notificationSent") : props.t("notificationNotSent")}</span>
              </div>
            ))}
            {props.history.length === 0 && <p className="empty-state compact">{props.t("noPassportSlotHistory")}</p>}
          </div>
        </div>
      ) : (
        <p className="empty-state compact">{props.t("noPassportSlotMonitor")}</p>
      )}
    </section>
  );
}

function ProfilePanel(props: {
  user: User;
  profileForm: ProfileForm;
  setProfileForm: React.Dispatch<React.SetStateAction<ProfileForm>>;
  saveProfile: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  acceptCurrentTerms: () => Promise<void>;
  isBusy: boolean;
  t: (key: TranslationKey) => string;
  languageMode: LanguageMode;
}) {
  const form = props.profileForm;
  const [isTermsDialogOpen, setIsTermsDialogOpen] = useState(false);
  const openTerms = async () => {
    try {
      await props.acceptCurrentTerms();
    } catch {
      // 条款弹窗本身仍可查看；后台记录失败会在下一次点击时重试。
    }
    setIsTermsDialogOpen(true);
  };
  return (
    <section className="panel narrow-panel profile-panel">
      <div className="panel-title">
        <h2 className="headline">{props.t("personalInfo")}</h2>
      </div>
      <div className="account-tier-card">
        <Metric label={props.t("accountTierCurrent")} value={formatAccountTier(props.user.account_tier, props.t)} />
        <p className="form-intro compact">{props.t("accountTierLimits")}</p>
      </div>
      <div className="terms-profile-card">
        <div className="support-title">
          <Shield size={16} />
          <span>{props.t("termsTitle")}</span>
        </div>
        <p>{props.t("profileTermsIntro")}</p>
        <button type="button" className="button secondary compact-button" onClick={openTerms}>
          {props.t("viewTerms")}
        </button>
      </div>
      <form className="stack" onSubmit={props.saveProfile}>
        <label>
          {props.t("email")}
          <input
            value={form.email}
            onChange={(event) => props.setProfileForm({ ...form, email: event.target.value.trim() })}
            type="email"
            required
          />
        </label>
        <label>
          {props.languageMode === "zh" ? "当前密码" : "Current password"}
          <input
            value={form.currentPassword}
            onChange={(event) => props.setProfileForm({ ...form, currentPassword: event.target.value })}
            type="password"
            required
            autoComplete="current-password"
          />
        </label>
        <div className="two-col">
          <label>
            {props.languageMode === "zh" ? "新密码" : "New password"}
            <input
              value={form.newPassword}
              onChange={(event) => props.setProfileForm({ ...form, newPassword: event.target.value })}
              type="password"
              minLength={8}
              autoComplete="new-password"
            />
          </label>
          <label>
            {props.languageMode === "zh" ? "确认新密码" : "Confirm new password"}
            <input
              value={form.confirmPassword}
              onChange={(event) => props.setProfileForm({ ...form, confirmPassword: event.target.value })}
              type="password"
              minLength={8}
              autoComplete="new-password"
            />
          </label>
        </div>
        <div>
          <button className="button primary" disabled={props.isBusy}>{props.t("save")}</button>
        </div>
      </form>
      {isTermsDialogOpen && <TermsDialog t={props.t} languageMode={props.languageMode} onClose={() => setIsTermsDialogOpen(false)} />}
    </section>
  );
}

function AdminPanel(props: {
  users: AdminUser[];
  queryRuns: QueryRun[];
  queryJobs: AdminQueryJob[];
  scheduledQueryJobs: AdminScheduledQueryJob[];
  finishedQueryJobs: AdminFinishedQueryJob[];
  securityEvents: SecurityEvent[];
  emailDeliveryLogs: EmailDeliveryLog[];
  cases: AdminCase[];
  reload: () => Promise<void>;
  t: (key: TranslationKey) => string;
  languageMode: LanguageMode;
  systemEmailConfig: SystemEmailConfig | null;
  systemEmailForm: SystemEmailForm;
  setSystemEmailForm: React.Dispatch<React.SetStateAction<SystemEmailForm>>;
  saveSystemEmail: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  updateAccountTier: (userId: number, accountTier: AccountTier) => Promise<void>;
  updateWorkerPriority: (userId: number, workerPriority: number) => Promise<void>;
  restoreCeacAutoQuery: (caseId: number) => Promise<void>;
  isBusy: boolean;
}) {
  const form = props.systemEmailForm;
  const [priorityDrafts, setPriorityDrafts] = useState<Record<number, string>>({});
  const [collapsedAdminUsers, setCollapsedAdminUsers] = useState<Record<number, boolean>>({});
  const [collapsedLogUsers, setCollapsedLogUsers] = useState<Record<string, boolean>>({});
  const [collapsedSecurityActors, setCollapsedSecurityActors] = useState<Record<string, boolean>>({});
  const [collapsedEmailRecipients, setCollapsedEmailRecipients] = useState<Record<string, boolean>>({});
  const [isFinishedQueueCollapsed, setIsFinishedQueueCollapsed] = useState(true);
  const [queueClockMs, setQueueClockMs] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setQueueClockMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const casesByUserId = useMemo(() => {
    const grouped = new Map<number, AdminCase[]>();
    for (const item of props.cases) {
      grouped.set(item.userId, [...(grouped.get(item.userId) ?? []), item]);
    }
    return grouped;
  }, [props.cases]);
  const queryRunsByUser = useMemo(() => {
    const grouped = new Map<string, QueryRun[]>();
    for (const run of props.queryRuns) {
      const email = run.user_email || props.t("triggerUnknown");
      grouped.set(email, [...(grouped.get(email) ?? []), run]);
    }
    return Array.from(grouped.entries()).sort(([emailA], [emailB]) => emailA.localeCompare(emailB));
  }, [props.queryRuns, props.t]);
  const securityEventsByActor = useMemo(() => {
    const grouped = new Map<string, { label: string; events: SecurityEvent[] }>();
    for (const event of props.securityEvents) {
      const key = event.user_email?.toLowerCase() || event.email_hash || event.actor_summary || event.device_hash || props.t("triggerUnknown");
      const current = grouped.get(key);
      const nextLabel = event.user_email || current?.label || event.actor_summary || event.email_hash.slice(0, 12) || props.t("triggerUnknown");
      grouped.set(key, { label: nextLabel, events: [...(current?.events ?? []), event] });
    }
    return Array.from(grouped.entries())
      .map(([key, value]) => ({ key, label: value.label, events: value.events }))
      .sort((groupA, groupB) => groupA.label.localeCompare(groupB.label));
  }, [props.securityEvents, props.t]);
  const emailDeliveriesByRecipient = useMemo(() => {
    const grouped = new Map<string, EmailDeliveryLog[]>();
    for (const delivery of props.emailDeliveryLogs) {
      const recipient = delivery.recipient || props.t("triggerUnknown");
      grouped.set(recipient, [...(grouped.get(recipient) ?? []), delivery]);
    }
    return Array.from(grouped.entries()).sort(([recipientA], [recipientB]) => recipientA.localeCompare(recipientB));
  }, [props.emailDeliveryLogs, props.t]);
  const toggleLogUser = (email: string) => {
    setCollapsedLogUsers((current) => ({ ...current, [email]: !current[email] }));
  };
  const toggleAdminUser = (userId: number) => {
    setCollapsedAdminUsers((current) => ({ ...current, [userId]: !(current[userId] ?? true) }));
  };
  const toggleSecurityActor = (actor: string) => {
    setCollapsedSecurityActors((current) => ({ ...current, [actor]: !(current[actor] ?? true) }));
  };
  const toggleEmailRecipient = (recipient: string) => {
    setCollapsedEmailRecipients((current) => ({ ...current, [recipient]: !(current[recipient] ?? true) }));
  };
  const toggleFinishedQueue = () => {
    setIsFinishedQueueCollapsed((current) => !current);
  };
  const currentJobWaitSeconds = (job: AdminQueryJob) => {
    const baseValue = job.status === "running" ? job.started_at : job.created_at;
    const baseMs = baseValue ? Date.parse(baseValue) : Number.NaN;
    if (Number.isNaN(baseMs)) {
      return job.wait_seconds;
    }
    return Math.max(0, Math.floor((queueClockMs - baseMs) / 1000));
  };
  const scheduledJobSecondsUntilQueue = (job: AdminScheduledQueryJob) => {
    const nextMs = Date.parse(job.next_check_at);
    if (Number.isNaN(nextMs)) {
      return job.seconds_until_queue;
    }
    return Math.max(0, Math.ceil((nextMs - queueClockMs) / 1000));
  };
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-title">
          <div>
            <h2 className="headline">{props.t("systemEmail")}</h2>
            {props.systemEmailConfig && (
              <p className="form-intro">
                {props.t("systemEmailSource")}: {props.systemEmailConfig.source}
                {" · "}
                {props.systemEmailConfig.isConfigured ? props.t("systemEmailConfigured") : props.t("systemEmailNotConfigured")}
              </p>
            )}
          </div>
        </div>
        <form className="stack" onSubmit={props.saveSystemEmail}>
          <div className="two-col">
            <label>
              {props.t("smtpEmail")}
              <input
                value={form.fromEmail}
                onChange={(event) => props.setSystemEmailForm({ ...form, fromEmail: event.target.value.trim() })}
                type="email"
                required
              />
            </label>
            <label>
              {props.t("passwordOrCode")}
              <input
                value={form.password}
                onChange={(event) => props.setSystemEmailForm({ ...form, password: event.target.value })}
                type="password"
                placeholder={props.systemEmailConfig?.hasPassword ? props.t("keepPasswordPlaceholder") : ""}
              />
            </label>
          </div>
          <div className="two-col">
            <label>
              {props.t("smtpHost")}
              <input
                value={form.host}
                onChange={(event) => props.setSystemEmailForm({ ...form, host: event.target.value.trim() })}
                required
              />
            </label>
            <label>
              {props.t("smtpPort")}
              <input
                value={form.port}
                onChange={(event) => props.setSystemEmailForm({ ...form, port: event.target.value })}
                inputMode="numeric"
                required
              />
            </label>
          </div>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.useSsl}
              onChange={(event) => props.setSystemEmailForm({ ...form, useSsl: event.target.checked })}
            />
            <span>{props.t("useSsl")}</span>
          </label>
          <div>
            <button className="button primary" disabled={props.isBusy}>{props.t("save")}</button>
          </div>
        </form>
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2 className="headline">{props.t("adminUsers")}</h2>
        </div>
        <div className="admin-user-list">
          {props.users.map((adminUser) => {
            const ownedCases = casesByUserId.get(adminUser.id) ?? [];
            const isCollapsed = collapsedAdminUsers[adminUser.id] ?? true;
            return (
              <div key={adminUser.id} className={`admin-user-card ${isCollapsed ? "collapsed" : ""}`}>
                <button type="button" className="admin-user-header" onClick={() => toggleAdminUser(adminUser.id)}>
                  <span className="admin-user-title">
                    {isCollapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
                    <span>
                      <span className="case-name">{adminUser.email}</span>
                      <span className="case-meta">
                        {adminUser.role} · {formatAccountTier(adminUser.account_tier, props.t)} · {adminUser.is_email_verified ? props.t("verified") : props.t("notVerified")} · {props.t("workerPriority")} {adminUser.worker_priority}
                      </span>
                    </span>
                  </span>
                  <span className="admin-user-summary">
                    <span className={`status-badge ${adminUser.account_tier === "premium" ? "success" : ""}`}>
                      {formatAccountTier(adminUser.account_tier, props.t)}
                    </span>
                    <span className="status-badge">{adminUser.case_count} {props.t("casesOwned")}</span>
                  </span>
                </button>
                {!isCollapsed && (
                  <>
                    <div className="admin-controls-row">
                      <label>
                        {props.t("accountTier")}
                        <select
                          value={adminUser.account_tier}
                          onChange={(event) => props.updateAccountTier(adminUser.id, event.target.value as AccountTier)}
                          disabled={props.isBusy}
                        >
                          <option value="standard">{props.t("accountTierStandard")}</option>
                          <option value="premium">{props.t("accountTierPremium")}</option>
                        </select>
                      </label>
                      <label>
                        {props.t("workerPriority")}
                        <input
                          type="number"
                          min={1}
                          max={999}
                          value={priorityDrafts[adminUser.id] ?? String(adminUser.worker_priority)}
                          onChange={(event) => setPriorityDrafts({ ...priorityDrafts, [adminUser.id]: event.target.value })}
                        />
                      </label>
                      <button
                        type="button"
                        className="button secondary"
                        disabled={props.isBusy}
                        onClick={() => props.updateWorkerPriority(adminUser.id, Number(priorityDrafts[adminUser.id] ?? adminUser.worker_priority))}
                      >
                        {props.t("saveWorkerPriority")}
                      </button>
                    </div>
                    <p className="form-intro compact">{props.t("workerPriorityHint")}</p>
                    <div className="admin-user-metrics">
                      <Metric label={props.t("lastQuery")} value={formatTime(adminUser.last_checked_at, props.languageMode)} />
                      <Metric label={props.t("createdAt")} value={formatTime(adminUser.created_at, props.languageMode)} />
                      <Metric label={props.t("updatedAt")} value={formatTime(adminUser.updated_at, props.languageMode)} />
                    </div>
                    <div className="case-list compact">
                      {ownedCases.map((item) => {
                        const key = item.adminCaseKey ?? `${item.profileType ?? "ceac"}-${item.id}`;
                        const isIrcc = item.profileType === "ircc";
                        const isKorea = item.profileType === "korea";
                        const countryLabel = isKorea ? props.t("countryKorea") : isIrcc ? props.t("countryCanada") : props.t("countryUnitedStates");
                        const statusSummary = item.lastStatus ?? props.t("waitFirstQuery");
                        const irccPrimarySummary = item.statusOverview
                          ? formatIrccHeadline(item.statusOverview, props.languageMode)
                          : statusSummary;
                        const irccSecondarySummary = item.statusOverview?.overallCode
                          ? `${props.t("irccOverallStatus")}: ${formatIrccCode(item.statusOverview.overallCode, props.languageMode)}`
                          : "";
                        return (
                          <div key={key} className="admin-profile-card">
                            <div className="admin-profile-main">
                              <span className="admin-profile-title">{item.displayName}</span>
                              <div className="admin-profile-meta">
                                <span className="admin-country-badge">{countryLabel}</span>
                                <span className="mono-text">{item.applicationNum}</span>
                              </div>
                            </div>
                            <div className="admin-profile-status">
                              {isIrcc ? (
                                <>
                                  <div className="admin-profile-status-line">
                                    <span className={getIrccToneBadgeClass(item.statusOverview?.tone)} title={irccPrimarySummary}>
                                      {irccPrimarySummary}
                                    </span>
                                  </div>
                                  {irccSecondarySummary && (
                                    <div className="admin-profile-subline admin-ircc-subline" title={irccSecondarySummary}>
                                      {irccSecondarySummary}
                                    </div>
                                  )}
                                </>
                              ) : isKorea ? (
                                <div className="admin-profile-status-line">
                                  <span className={getStatusBadgeClass(item.lastStatus)}>
                                    {statusSummary}
                                  </span>
                                </div>
                              ) : (
                                <>
                                  <div className="admin-profile-status-line">
                                    <span className={getStatusBadgeClass(item.lastStatus)}>
                                      {statusSummary}
                                    </span>
                                    {item.passportSlotMonitor && (
                                      <span className="admin-inline-meta">
                                        GTS: {formatPassportSlotStatus(item.passportSlotMonitor.lastResult, props.t)}
                                      </span>
                                    )}
                                  </div>
                                  {item.passportSlotMonitor && (
                                    <div className="admin-profile-subline">
                                      <span>slot {item.passportSlotMonitor.lastSlotCount}</span>
                                      <span>{props.t("nextCheckAt")}: {formatTime(item.passportSlotMonitor.nextCheckAt, props.languageMode)}</span>
                                    </div>
                                  )}
                                </>
                              )}
                            </div>
                            <div className="admin-profile-side">
                              <span className="mono-text">{formatTime(item.lastCheckedAt, props.languageMode)}</span>
                              {!isIrcc && !isKorea && item.passportSlotMonitor?.lastErrorMessage && (
                                <span className="status-badge error">{item.passportSlotMonitor.lastErrorMessage}</span>
                              )}
                              {!isIrcc && !isKorea && item.ceacAutoLockedByPassportSlot && (
                                <button
                                  type="button"
                                  className="button secondary compact-button"
                                  disabled={props.isBusy}
                                  onClick={() => props.restoreCeacAutoQuery(item.id)}
                                >
                                  {props.t("restoreCeacAutoQuery")}
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                      {ownedCases.length === 0 && <p className="empty-state compact">{props.t("noCases")}</p>}
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2 className="headline">{props.t("workerQueue")}</h2>
        </div>
        <h3 className="subhead compact-heading">{props.t("workerQueueCurrent")}</h3>
        {props.queryJobs.length > 0 ? (
          <div className="log-table-wrap">
            <table className="log-table">
              <thead>
                <tr>
                  <th>{props.t("queuePosition")}</th>
                  <th>{props.t("email")}</th>
                  <th>{props.t("profile")}</th>
                  <th>{props.t("applicationId")}</th>
                  <th>{props.t("lastCheckMode")}</th>
                  <th>{props.t("workerPriority")}</th>
                  <th>{props.t("workerStatus")}</th>
                  <th>{props.t("createdAt")}</th>
                  <th>{props.t("queueWait")}</th>
                  <th>{props.t("workerLockedBy")}</th>
                </tr>
              </thead>
              <tbody>
                {props.queryJobs.map((job) => (
                  <tr key={job.id}>
                    <td className="mono-text">{job.queue_position}</td>
                    <td>{job.user_email}</td>
                    <td>{job.display_name}</td>
                    <td className="mono-text">{job.application_num}</td>
                    <td>{formatTriggerType(job.trigger_type, props.t)}</td>
                    <td className="mono-text">{job.worker_priority}</td>
                    <td>
                      <span className={`status-badge ${job.status === "running" ? "success" : ""}`}>{job.status}</span>
                    </td>
                    <td>{formatTime(job.created_at, props.languageMode)}</td>
                    <td className="mono-text">{formatDurationSeconds(currentJobWaitSeconds(job))}</td>
                    <td className="mono-text">{job.locked_by || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty-state">{props.t("workerQueueEmpty")}</p>
        )}

        <h3 className="subhead compact-heading spaced">{props.t("workerScheduledQueue")}</h3>
        {props.scheduledQueryJobs.length > 0 ? (
          <div className="log-table-wrap">
            <table className="log-table">
              <thead>
                <tr>
                  <th>{props.t("scheduledPosition")}</th>
                  <th>{props.t("email")}</th>
                  <th>{props.t("profile")}</th>
                  <th>{props.t("applicationId")}</th>
                  <th>{props.t("lastCheckMode")}</th>
                  <th>{props.t("workerPriority")}</th>
                  <th>{props.t("expectedQueueAt")}</th>
                  <th>{props.t("timeUntilQueue")}</th>
                </tr>
              </thead>
              <tbody>
                {props.scheduledQueryJobs.map((job) => (
                  <tr key={job.scheduled_id}>
                    <td className="mono-text">{job.schedule_position}</td>
                    <td>{job.user_email}</td>
                    <td>{job.display_name}</td>
                    <td className="mono-text">{job.application_num}</td>
                    <td>{formatTriggerType(job.trigger_type, props.t)}</td>
                    <td className="mono-text">{job.worker_priority}</td>
                    <td>{formatTime(job.next_check_at, props.languageMode)}</td>
                    <td className="mono-text">{formatDurationSeconds(scheduledJobSecondsUntilQueue(job))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty-state">{props.t("workerScheduledQueueEmpty")}</p>
        )}

        <button type="button" className="subsection-toggle spaced" onClick={toggleFinishedQueue}>
          <span className="log-group-title">
            {isFinishedQueueCollapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
            <span>{props.t("workerFinishedQueue")}</span>
          </span>
          <span className="status-badge">{props.finishedQueryJobs.length} {props.t("logItems")}</span>
        </button>
        {!isFinishedQueueCollapsed && props.finishedQueryJobs.length > 0 ? (
          <div className="log-table-wrap">
            <table className="log-table">
              <thead>
                <tr>
                  <th>{props.t("queuePosition")}</th>
                  <th>{props.t("email")}</th>
                  <th>{props.t("profile")}</th>
                  <th>{props.t("applicationId")}</th>
                  <th>{props.t("lastCheckMode")}</th>
                  <th>{props.t("workerStatus")}</th>
                  <th>{props.t("finishedAt")}</th>
                  <th>{props.t("duration")}</th>
                  <th>{props.t("workerLockedBy")}</th>
                </tr>
              </thead>
              <tbody>
                {props.finishedQueryJobs.map((job) => (
                  <tr key={job.id}>
                    <td className="mono-text">{job.finished_position}</td>
                    <td>{job.user_email}</td>
                    <td>{job.display_name}</td>
                    <td className="mono-text">{job.application_num}</td>
                    <td>{formatTriggerType(job.trigger_type, props.t)}</td>
                    <td>
                      <span className={`status-badge ${job.status === "succeeded" ? "success" : "error"}`}>{job.status}</span>
                    </td>
                    <td>{formatTime(job.finished_at, props.languageMode)}</td>
                    <td className="mono-text">{formatDurationSeconds(job.duration_seconds)}</td>
                    <td className="mono-text">{job.locked_by || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : !isFinishedQueueCollapsed ? (
          <p className="empty-state">{props.t("workerFinishedQueueEmpty")}</p>
        ) : null}
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2 className="headline">{props.t("systemLogs")}</h2>
          <button className="button secondary" onClick={props.reload}>{props.t("refresh")}</button>
        </div>
        <div className="log-groups">
          {queryRunsByUser.map(([email, runs]) => {
            const isCollapsed = collapsedLogUsers[email] ?? true;
            return (
              <section key={email} className={`log-group ${isCollapsed ? "collapsed" : ""}`}>
                <button type="button" className="log-group-header" onClick={() => toggleLogUser(email)}>
                  <span className="log-group-title">
                    {isCollapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
                    <span>{email}</span>
                  </span>
                  <span className="status-badge">{runs.length} {props.t("logItems")}</span>
                </button>
                {!isCollapsed && (
                  <div className="log-table-wrap">
                    <table className="log-table">
                      <thead>
                        <tr>
                          <th>{props.t("lastCheckedAt")}</th>
                          <th>{props.t("executor")}</th>
                          <th>{props.t("profile")}</th>
                          <th>{props.t("applicationId")}</th>
                          <th>{props.t("lastCheckMode")}</th>
                          <th>{props.t("status")}</th>
                          <th>{props.t("duration")}</th>
                          <th>{props.t("changeContent")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {runs.map((run) => (
                          <tr key={run.id}>
                            <td>{formatTime(run.finished_at, props.languageMode)}</td>
                            <td>{run.user_email}</td>
                            <td>{run.display_name}</td>
                            <td className="mono-text">{run.application_num}</td>
                            <td>{formatTriggerType(run.trigger_type, props.t)}</td>
                            <td>
                              <span className={`status-badge ${run.success ? "success" : "error"}`}>
                                {run.success ? props.t("success") : props.t("error")}
                              </span>
                            </td>
                            <td className="mono-text">{run.duration_ms}ms</td>
                            <td>
                              {run.profile_type === "ircc" && run.status ? (
                                <span className="admin-ircc-summary">{translateIrccChangeSummary(run.status, props.languageMode)}</span>
                              ) : run.profile_type === "passport_slot" && run.status ? (
                                <span className="admin-ircc-summary">{formatInlineTimes(run.status, props.languageMode)}</span>
                              ) : run.status ? (
                                <span className={getStatusBadgeClass(run.status)}>{run.status}</span>
                              ) : (
                                run.error_message || props.t("noStatusChange")
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="log-card-list">
                      {runs.map((run) => (
                        <div key={run.id} className="log-card">
                          <div className="log-card-header">
                            <span>{formatTime(run.finished_at, props.languageMode)}</span>
                            <span className={`status-badge ${run.success ? "success" : "error"}`}>
                              {run.success ? props.t("success") : props.t("error")}
                            </span>
                          </div>
                          <div className="log-card-grid">
                            <Metric label={props.t("executor")} value={run.user_email} />
                            <Metric label={props.t("profile")} value={run.display_name} />
                            <Metric label={props.t("applicationId")} value={run.application_num} />
                            <Metric label={props.t("lastCheckMode")} value={formatTriggerType(run.trigger_type, props.t)} />
                            <Metric label={props.t("duration")} value={`${run.duration_ms}ms`} />
                            <Metric label={props.t("changeContent")}>
                              {run.profile_type === "ircc" && run.status ? (
                                <span className="admin-ircc-summary">{translateIrccChangeSummary(run.status, props.languageMode)}</span>
                              ) : run.profile_type === "passport_slot" && run.status ? (
                                <span className="admin-ircc-summary">{formatInlineTimes(run.status, props.languageMode)}</span>
                              ) : run.status ? (
                                <span className={getStatusBadgeClass(run.status, "metric-status")}>{run.status}</span>
                              ) : (
                                run.error_message || props.t("noStatusChange")
                              )}
                            </Metric>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </section>
            );
          })}
          {props.queryRuns.length === 0 && <p className="empty-state">{props.t("noLogs")}</p>}
        </div>
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2 className="headline">{props.t("emailDeliveryLogs")}</h2>
          <button className="button secondary" onClick={props.reload}>{props.t("refresh")}</button>
        </div>
        <div className="log-groups">
          {emailDeliveriesByRecipient.map(([recipient, deliveries]) => {
            const isCollapsed = collapsedEmailRecipients[recipient] ?? true;
            return (
              <section key={recipient} className={`log-group ${isCollapsed ? "collapsed" : ""}`}>
                <button type="button" className="log-group-header" onClick={() => toggleEmailRecipient(recipient)}>
                  <span className="log-group-title">
                    {isCollapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
                    <span>{recipient}</span>
                  </span>
                  <span className="status-badge">{deliveries.length} {props.t("logItems")}</span>
                </button>
                {!isCollapsed && (
                  <div className="log-card-list visible">
                    {deliveries.map((delivery) => (
                      <div key={delivery.id} className="log-card">
                        <div className="log-card-header">
                          <span>{formatTime(delivery.created_at, props.languageMode)}</span>
                          <span className="status-badge">{delivery.email_type}</span>
                        </div>
                        <div className="log-card-grid">
                          <Metric label={props.t("recipient")} value={delivery.recipient} />
                          <Metric label={props.t("executor")} value={delivery.user_email} />
                          <Metric label={props.t("profile")} value={delivery.display_name || "-"} />
                          <Metric label={props.t("emailType")} value={delivery.email_type} />
                          <Metric label={props.t("subject")} value={delivery.subject} />
                        </div>
                        <div className="email-body-preview">
                          <span className="caption">{props.t("body")}</span>
                          <pre>{delivery.body || props.t("emailDeliveryEmptyBody")}</pre>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            );
          })}
          {props.emailDeliveryLogs.length === 0 && <p className="empty-state">{props.t("noLogs")}</p>}
        </div>
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2 className="headline">{props.t("securityEvents")}</h2>
          <button className="button secondary" onClick={props.reload}>{props.t("refresh")}</button>
        </div>
        <div className="log-groups">
          {securityEventsByActor.map((group) => {
            const isCollapsed = collapsedSecurityActors[group.key] ?? true;
            return (
              <section key={group.key} className={`log-group ${isCollapsed ? "collapsed" : ""}`}>
                <button type="button" className="log-group-header" onClick={() => toggleSecurityActor(group.key)}>
                  <span className="log-group-title">
                    {isCollapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
                    <span>{group.label}</span>
                  </span>
                  <span className="status-badge">{group.events.length} {props.t("logItems")}</span>
                </button>
                {!isCollapsed && (
                  <div className="log-card-list visible">
                    {group.events.map((event) => (
                      <div key={event.id} className="log-card">
                        <div className="log-card-header">
                          <span>{formatTime(event.created_at, props.languageMode)}</span>
                          <span className={`status-badge ${event.severity === "warning" || event.severity === "error" ? "error" : "success"}`}>
                            {event.severity}
                          </span>
                        </div>
                        <div className="log-card-grid">
                          <Metric label={props.t("securityEventType")} value={event.event_type} />
                          <Metric label={props.t("securityActor")} value={event.actor_summary || event.user_email || props.t("triggerUnknown")} />
                          <Metric label={props.t("email")} value={event.user_email || props.t("triggerUnknown")} />
                          <Metric label={props.t("securitySeverity")} value={event.severity} />
                          <Metric label="Path" value={event.path || "-"} />
                          <Metric label={props.t("changeContent")} value={event.detail || "-"} />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            );
          })}
          {props.securityEvents.length === 0 && <p className="empty-state">{props.t("noLogs")}</p>}
        </div>
      </section>
    </div>
  );
}

function NewProfileForm(props: {
  country: ProfileCountry;
  setCountry: (country: ProfileCountry) => void;
  caseForm: CaseForm;
  setCaseForm: React.Dispatch<React.SetStateAction<CaseForm>>;
  saveCase: (e: FormEvent<HTMLFormElement>) => Promise<void>;
  irccCaseForm: IrccCaseForm;
  setIrccCaseForm: React.Dispatch<React.SetStateAction<IrccCaseForm>>;
  saveIrccCase: (e: FormEvent<HTMLFormElement>) => Promise<void>;
  koreaCaseForm: KoreaCaseForm;
  setKoreaCaseForm: React.Dispatch<React.SetStateAction<KoreaCaseForm>>;
  saveKoreaCase: (e: FormEvent<HTMLFormElement>) => Promise<void>;
  discoverIrccApplications: (e?: FormEvent<HTMLFormElement>) => Promise<void>;
  irccApplications: IrccDiscoveredApplication[];
  isBusy: boolean;
  t: (key: TranslationKey) => string;
  languageMode: LanguageMode;
}) {
  return (
    <div className="stack">
      <div className="country-cards">
        <button type="button" className={`country-card ${props.country === "us" ? "selected" : ""}`} onClick={() => props.setCountry("us")}>
          <div className="country-card-icon"><Landmark className="icon" size={24} /></div>
          <span>{props.t("countryUnitedStates")}</span>
        </button>
        <button type="button" className={`country-card ${props.country === "ca" ? "selected" : ""}`} onClick={() => props.setCountry("ca")}>
          <div className="country-card-icon"><TreePine className="icon" size={24} /></div>
          <span>{props.t("countryCanada")}</span>
        </button>
        <button type="button" className={`country-card ${props.country === "kr" ? "selected" : ""}`} onClick={() => props.setCountry("kr")}>
          <div className="country-card-icon"><LucideMap className="icon" size={24} /></div>
          <span>{props.t("countryKorea")}</span>
        </button>
      </div>
      {props.country === "us" ? (
        <CaseFormView caseForm={props.caseForm} setCaseForm={props.setCaseForm} saveCase={props.saveCase} isBusy={props.isBusy} t={props.t} languageMode={props.languageMode} />
      ) : props.country === "ca" ? (
        <IrccCaseFormView
          form={props.irccCaseForm}
          setForm={props.setIrccCaseForm}
          saveCase={props.saveIrccCase}
          discoverApplications={props.discoverIrccApplications}
          applications={props.irccApplications}
          isBusy={props.isBusy}
          t={props.t}
        />
      ) : (
        <KoreaCaseFormView
          form={props.koreaCaseForm}
          setForm={props.setKoreaCaseForm}
          saveCase={props.saveKoreaCase}
          isBusy={props.isBusy}
          t={props.t}
        />
      )}
    </div>
  );
}

function IrccCaseFormView(props: {
  form: IrccCaseForm;
  setForm: React.Dispatch<React.SetStateAction<IrccCaseForm>>;
  saveCase: (e: FormEvent<HTMLFormElement>) => Promise<void>;
  discoverApplications: (e?: FormEvent<HTMLFormElement>) => Promise<void>;
  applications: IrccDiscoveredApplication[];
  isBusy: boolean;
  t: (key: TranslationKey) => string;
}) {
  const form = props.form;
  const setForm = props.setForm;
  return (
    <form className="stack" onSubmit={props.saveCase}>
      <div className="official-form-note alpha-note">
        <strong>{props.t("irccPortalTitle")}</strong>
        <span>{props.t("irccAlphaLabel")}</span>
      </div>
      <p className="section-help">{props.t("irccPortalIntro")}</p>
      <div className="form-section">
        <label>
          {props.t("caseName")}
          <input value={form.displayName} onChange={(e) => setForm({ ...form, displayName: e.target.value })} required placeholder="例如：加拿大 TRV" />
        </label>
        <div className="two-col">
          <label>
            {props.t("irccPortalEmail")}
            <input value={form.portalEmail} onChange={(e) => setForm({ ...form, portalEmail: e.target.value.trim() })} type="email" required />
          </label>
          <label>
            {props.t("irccPortalPassword")}
            <input value={form.portalPassword} onChange={(e) => setForm({ ...form, portalPassword: e.target.value })} type="password" required />
          </label>
        </div>
        <button type="button" className="button secondary" onClick={() => props.discoverApplications()} disabled={props.isBusy || !form.portalEmail || !form.portalPassword}>
          <Activity size={16} /> {props.t("irccDiscoverApplications")}
        </button>
        {props.applications.length > 0 && (
          <label>
            {props.t("irccApplicationSelect")}
            <select
              className="select-input"
              value={form.appId}
              onChange={(event) => {
                const selected = props.applications.find((item) => item.appId === event.target.value);
                if (!selected) {
                  return;
                }
                setForm({
                  ...form,
                  appId: selected.appId,
                  applicationNumber: selected.applicationNumber,
                  principalApplicant: selected.principalApplicant,
                  displayName: form.displayName || `IRCC ${selected.applicationNumber || selected.appId}`,
                });
              }}
            >
              {props.applications.map((application) => (
                <option key={application.appId} value={application.appId}>
                  {application.applicationNumber || application.appId} · {application.principalApplicant || application.status}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="two-col">
          <label>
            {props.t("irccAppId")}
            <input value={form.appId} onChange={(e) => setForm({ ...form, appId: e.target.value.trim() })} required />
          </label>
          <label>
            {props.t("irccApplicationNumber")}
            <input value={form.applicationNumber} onChange={(e) => setForm({ ...form, applicationNumber: e.target.value.trim().toUpperCase() })} />
          </label>
        </div>
        <label>
          {props.t("irccPrincipalApplicant")}
          <input value={form.principalApplicant} onChange={(e) => setForm({ ...form, principalApplicant: e.target.value })} />
        </label>
      </div>
      <div className="form-section">
        <p className="section-help">{props.t("deliverySection")}</p>
        <label>
          {props.t("deliveryEmail")}
          <input value={form.receiveEmail} onChange={(e) => setForm({ ...form, receiveEmail: e.target.value.trim() })} type="email" required={form.emailNotificationsEnabled} />
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={form.isEnabled} onChange={(e) => setForm({ ...form, isEnabled: e.target.checked })} />
          <span className="body-sm">{props.t("autoMonitor")}</span>
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={form.emailNotificationsEnabled} onChange={(e) => setForm({ ...form, emailNotificationsEnabled: e.target.checked })} />
          <span className="body-sm">{props.t("emailPushSetting")}</span>
        </label>
        <label>
          {props.t("senderConfig")}
          <div className="segmented">
            <button type="button" className={form.senderMode === "system" ? "selected" : ""} onClick={() => setForm({ ...form, senderMode: "system" })}>{props.t("systemSender")}</button>
            <button type="button" className={form.senderMode === "custom" ? "selected" : ""} onClick={() => setForm({ ...form, senderMode: "custom" })}>{props.t("useCustomSmtp")}</button>
          </div>
        </label>
        {form.senderMode === "custom" && (
          <div className="smtp-box">
            <label>{props.t("smtpEmail")} <input value={form.smtpFromEmail} onChange={(e) => setForm({ ...form, smtpFromEmail: e.target.value })} type="email" required /></label>
            <div className="two-col">
              <label>{props.t("smtpHost")} <input value={form.smtpHost} onChange={(e) => setForm({ ...form, smtpHost: e.target.value })} required /></label>
              <label>{props.t("smtpPort")} <input value={form.smtpPort} onChange={(e) => setForm({ ...form, smtpPort: e.target.value })} required /></label>
            </div>
            <label>{props.t("passwordOrCode")} <input value={form.smtpPassword} onChange={(e) => setForm({ ...form, smtpPassword: e.target.value })} type="password" required /></label>
            <label className="checkbox"><input type="checkbox" checked={form.smtpUseSsl} onChange={(e) => setForm({ ...form, smtpUseSsl: e.target.checked })} /> <span>{props.t("useSsl")}</span></label>
          </div>
        )}
      </div>
      <button className="button primary" disabled={props.isBusy}>{props.t("irccSave")}</button>
    </form>
  );
}

function KoreaCaseFormView(props: {
  form: KoreaCaseForm;
  setForm: React.Dispatch<React.SetStateAction<KoreaCaseForm>>;
  saveCase: (e: FormEvent<HTMLFormElement>) => Promise<void>;
  isBusy: boolean;
  t: (key: TranslationKey) => string;
}) {
  const form = props.form;
  const setForm = props.setForm;
  return (
    <form className="stack" onSubmit={props.saveCase}>
      <div className="official-form-note alpha-note">
        <strong>{props.t("koreaVisaTitle")}</strong>
        <span>{props.t("irccAlphaLabel")}</span>
      </div>
      <div className="form-section">
        <p className="section-help">{props.t("koreaQueryHint")}</p>
        <label>
          {props.t("caseName")}
          <input value={form.displayName} onChange={(e) => setForm({ ...form, displayName: e.target.value })} required placeholder="例如：韩国签证" />
        </label>
        <div className="two-col">
          <label>
            {props.t("passport")}
            <input value={form.passportNumber} onChange={(e) => setForm({ ...form, passportNumber: e.target.value.trim().toUpperCase() })} required placeholder={props.t("passportPlaceholder")} />
          </label>
          <label>
            {props.t("koreaBirthDate")}
            <input value={form.birthDate} onChange={(e) => setForm({ ...form, birthDate: e.target.value.trim() })} required type="date" placeholder="YYYY-MM-DD" />
          </label>
        </div>
        <label>
          {props.t("koreaEnglishName")}
          <input value={form.englishName} onChange={(e) => setForm({ ...form, englishName: e.target.value.toUpperCase() })} required placeholder="ZHANG SAN" />
          <span className="field-hint">{props.t("koreaNameHint")}</span>
        </label>
      </div>
      <div className="form-section">
        <p className="section-help">{props.t("deliverySection")}</p>
        <label>
          {props.t("deliveryEmail")}
          <input value={form.receiveEmail} onChange={(e) => setForm({ ...form, receiveEmail: e.target.value.trim() })} type="email" required={form.emailNotificationsEnabled} />
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={form.isEnabled} onChange={(e) => setForm({ ...form, isEnabled: e.target.checked })} />
          <span className="body-sm">{props.t("autoMonitor")}</span>
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={form.emailNotificationsEnabled} onChange={(e) => setForm({ ...form, emailNotificationsEnabled: e.target.checked })} />
          <span className="body-sm">{props.t("emailPushSetting")}</span>
        </label>
        <label>
          {props.t("senderConfig")}
          <div className="segmented">
            <button type="button" className={form.senderMode === "system" ? "selected" : ""} onClick={() => setForm({ ...form, senderMode: "system" })}>{props.t("systemSender")}</button>
            <button type="button" className={form.senderMode === "custom" ? "selected" : ""} onClick={() => setForm({ ...form, senderMode: "custom" })}>{props.t("useCustomSmtp")}</button>
          </div>
        </label>
        {form.senderMode === "custom" && (
          <div className="smtp-box">
            <label>{props.t("smtpEmail")} <input value={form.smtpFromEmail} onChange={(e) => setForm({ ...form, smtpFromEmail: e.target.value })} type="email" required /></label>
            <div className="two-col">
              <label>{props.t("smtpHost")} <input value={form.smtpHost} onChange={(e) => setForm({ ...form, smtpHost: e.target.value })} required /></label>
              <label>{props.t("smtpPort")} <input value={form.smtpPort} onChange={(e) => setForm({ ...form, smtpPort: e.target.value })} required /></label>
            </div>
            <label>{props.t("passwordOrCode")} <input value={form.smtpPassword} onChange={(e) => setForm({ ...form, smtpPassword: e.target.value })} type="password" required /></label>
            <label className="checkbox"><input type="checkbox" checked={form.smtpUseSsl} onChange={(e) => setForm({ ...form, smtpUseSsl: e.target.checked })} /> <span>{props.t("useSsl")}</span></label>
          </div>
        )}
      </div>
      <button className="button primary" disabled={props.isBusy}>{props.t("koreaSave")}</button>
    </form>
  );
}

function CaseFormView(props: {
  caseForm: CaseForm;
  setCaseForm: React.Dispatch<React.SetStateAction<CaseForm>>;
  saveCase: (e: FormEvent<HTMLFormElement>) => Promise<void>;
  isBusy: boolean;
  t: (key: TranslationKey) => string;
  languageMode: LanguageMode;
}) {
  const form = props.caseForm;
  const setForm = props.setCaseForm;

  return (
    <form className="stack" onSubmit={props.saveCase}>
      <div className="official-form-note">
        <strong>{props.t("visaApplicationType")}</strong>
        <span>{props.t("visaTypeNiv")}</span>
      </div>

      <div className="form-section">
        <p className="section-help">{props.t("queryHint")}</p>
        <label>
          {props.t("caseName")}
          <input value={form.displayName} onChange={(e) => setForm({ ...form, displayName: e.target.value })} required placeholder={props.t("caseNamePlaceholder")} />
        </label>
        <label>
          {props.t("location")}
          <select
            value={form.location}
            onChange={(e) => setForm({ ...form, location: e.target.value })}
            required
            className="select-input"
          >
            {ceacLocations.map((location) => (
              <option key={location} value={location}>{location}</option>
            ))}
          </select>
        </label>
        <label>
          {props.t("applicationId")}
          <input value={form.applicationNum} onChange={(e) => setForm({ ...form, applicationNum: e.target.value.trim().toUpperCase() })} required placeholder="AA0020AKAX or 2012118 345 0001" />
          <span className="field-hint">(e.g., AA0020AKAX or 2012118 345 0001)</span>
        </label>
      </div>

      <div className="form-section">
        <p className="section-help">{props.t("pre2022Note")}</p>
      <div className="two-col">
        <label>
            {props.t("passport")}
            <input value={form.passportNumber} onChange={(e) => setForm({ ...form, passportNumber: e.target.value.trim().toUpperCase() })} required placeholder={props.t("passportPlaceholder")} />
          </label>
          <label>
            {props.t("firstFiveSurname")}
            <input
              value={form.surname}
              onChange={(e) => setForm({ ...form, surname: e.target.value.trim().toUpperCase().slice(0, 5) })}
              required
              maxLength={5}
              placeholder={props.languageMode === "zh" ? "姓的前五个字母，或 NA" : "First 5 letters or NA"}
            />
            <span className="field-hint">{props.t("firstFiveSurnameHint")}</span>
          </label>
        </div>
      </div>

      <div className="form-section">
        <p className="section-help">{props.t("deliverySection")}</p>
        <label>
          {props.t("deliveryEmail")}
          <input
            value={form.receiveEmail}
            onChange={(e) => setForm({ ...form, receiveEmail: e.target.value.trim() })}
            type="email"
            required={form.emailNotificationsEnabled}
          />
        </label>

      <label className="checkbox">
        <input type="checkbox" checked={form.isEnabled} onChange={(e) => setForm({ ...form, isEnabled: e.target.checked })} />
        <span className="body-sm">{props.t("autoMonitor")}</span>
      </label>

      <label className="checkbox">
        <input type="checkbox" checked={form.emailNotificationsEnabled} onChange={(e) => setForm({ ...form, emailNotificationsEnabled: e.target.checked })} />
        <span className="body-sm">{props.t("emailPushSetting")}</span>
      </label>

      <label>
        {props.t("senderConfig")}
        <div className="segmented">
          <button type="button" className={form.senderMode === "system" ? "selected" : ""} onClick={() => setForm({ ...form, senderMode: "system" })}>{props.t("systemSender")}</button>
          <button type="button" className={form.senderMode === "custom" ? "selected" : ""} onClick={() => setForm({ ...form, senderMode: "custom" })}>{props.t("useCustomSmtp")}</button>
        </div>
      </label>

      {form.senderMode === "custom" && (
        <div className="smtp-box">
          <label>{props.t("smtpEmail")} <input value={form.smtpFromEmail} onChange={(e) => setForm({ ...form, smtpFromEmail: e.target.value })} type="email" required /></label>
          <div className="two-col">
            <label>{props.t("smtpHost")} <input value={form.smtpHost} onChange={(e) => setForm({ ...form, smtpHost: e.target.value })} required /></label>
            <label>{props.t("smtpPort")} <input value={form.smtpPort} onChange={(e) => setForm({ ...form, smtpPort: e.target.value })} required /></label>
          </div>
          <label>{props.t("passwordOrCode")} <input value={form.smtpPassword} onChange={(e) => setForm({ ...form, smtpPassword: e.target.value })} type="password" required /></label>
          <label className="checkbox"><input type="checkbox" checked={form.smtpUseSsl} onChange={(e) => setForm({ ...form, smtpUseSsl: e.target.checked })} /> <span>{props.t("useSsl")}</span></label>
        </div>
      )}
      </div>

      <div style={{ marginTop: "16px" }}>
        <button className="button primary" disabled={props.isBusy}>{props.t("save")}</button>
      </div>
    </form>
  );
}

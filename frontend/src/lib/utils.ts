import { clsx, type ClassValue } from 'clsx';
import { formatDistanceToNow, parseISO, differenceInHours, differenceInDays } from 'date-fns';
import { ru } from 'date-fns/locale';

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function formatMoney(amount: number | null | undefined, currency = 'KZT'): string {
  if (amount == null) return '—';
  return new Intl.NumberFormat('ru-KZ', {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  }).format(amount);
}

export function formatDeadline(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  try {
    const date = parseISO(dateStr);
    const now = new Date();
    const diffDays = differenceInDays(date, now);
    const diffHours = differenceInHours(date, now);

    if (diffHours < 0) return 'Истёк';
    if (diffHours < 24) return `${diffHours} ч.`;
    if (diffDays < 7) return `${diffDays} дн.`;
    return date.toLocaleDateString('ru-KZ');
  } catch {
    return dateStr;
  }
}

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  try {
    return parseISO(dateStr).toLocaleDateString('ru-KZ', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

export function platformLabel(platform: string): string {
  return { goszakup: 'GosZakup', zakupsk: 'Zakup SK' }[platform] || platform;
}

export function categoryLabel(category: string | null): string {
  if (!category) return '—';
  return {
    product: 'Товар',
    software_service: 'IT / Разработка',
    other: 'Прочее',
  }[category] || category;
}

export function confidenceLabel(level: string | null): string {
  if (!level) return '—';
  return { high: 'Высокая', medium: 'Средняя', low: 'Низкая' }[level] || level;
}

export function confidenceColor(level: string | null): string {
  return {
    high:   'badge-green',
    medium: 'badge-yellow',
    low:    'badge-red',
  }[level || ''] || 'badge-gray';
}

export function riskColor(level: string | null): string {
  return {
    low:    'text-green-400',
    medium: 'text-yellow-400',
    high:   'text-red-400',
  }[level || ''] || 'text-gray-400';
}

export function marginColor(margin: number | null): string {
  if (margin == null) return 'text-gray-500';
  if (margin >= 70) return 'text-green-400';
  if (margin >= 50) return 'text-green-500';
  if (margin >= 30) return 'text-yellow-400';
  return 'text-red-400';
}

/** Returns the public URL to view a tender on its platform. */
export function platformTenderUrl(platform: string, externalId: string): string | null {
  if (!externalId) return null;
  if (platform === 'goszakup') {
    return `https://goszakup.gov.kz/ru/announce/index/${externalId}`;
  }
  if (platform === 'zakupsk') {
    return `https://zakup.sk.kz/ru/purchase/index/${externalId}`;
  }
  return null;
}

/** Build pagination page range: [1, …, 4, 5, 6, …, 20] */
export function buildPageRange(current: number, total: number): (number | '…')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages: (number | '…')[] = [];
  const addPage = (n: number) => {
    if (!pages.includes(n)) pages.push(n);
  };
  addPage(1);
  if (current > 3) pages.push('…');
  for (let i = Math.max(2, current - 2); i <= Math.min(total - 1, current + 2); i++) addPage(i);
  if (current < total - 2) pages.push('…');
  addPage(total);
  return pages;
}

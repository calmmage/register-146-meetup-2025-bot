import io
from collections import defaultdict

import pandas as pd
import seaborn as sns
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile
from matplotlib import pyplot as plt
from app.app import App
from app.routers.admin import _format_graduate_type
from app.routers.crm import router
from botspot import commands_menu, send_safe
from botspot.components.qol.bot_commands_menu import Visibility
from botspot.utils.admin_filter import AdminFilter


def get_median(ratios):
    if not ratios:
        return 0
    ratios.sort()
    return ratios[len(ratios) // 2]


@commands_menu.add_command("stats", "Статистика регистраций", visibility=Visibility.ADMIN_ONLY)
@router.message(Command("stats"), AdminFilter())
async def show_stats(message: Message, app: App):
    """Показать статистику регистраций"""

    from app.app import PAYMENT_STATUS_MAP

    # Initialize stats text
    stats_text = "<b>📊 Статистика регистраций</b> (включая удаленных)\n\n"

    # 1. Count registrations by city for both active and deleted users
    # Active users
    city_cursor = app.collection.aggregate(
        [{"$group": {"_id": "$target_city", "count": {"$sum": 1}}}]
    )
    active_city_stats = await city_cursor.to_list(length=None)

    # Deleted users
    deleted_city_cursor = app.deleted_users.aggregate(
        [{"$group": {"_id": "$target_city", "count": {"$sum": 1}}}]
    )
    deleted_city_stats = await deleted_city_cursor.to_list(length=None)

    # Combine city statistics
    city_stats_combined = {}
    for stat in active_city_stats:
        city = stat["_id"]
        count = stat["count"]
        city_stats_combined[city] = {"active": count, "deleted": 0}

    for stat in deleted_city_stats:
        city = stat["_id"]
        count = stat["count"]
        if city in city_stats_combined:
            city_stats_combined[city]["deleted"] = count
        else:
            city_stats_combined[city] = {"active": 0, "deleted": count}

    stats_text += "<b>🌆 По городам:</b>\n"
    total_active = 0
    total_deleted = 0

    for city, counts in sorted(city_stats_combined.items()):
        active_count = counts["active"]
        deleted_count = counts["deleted"]
        total_count = active_count + deleted_count

        total_active += active_count
        total_deleted += deleted_count

        deleted_note = f" (из них {deleted_count} удал.)" if deleted_count > 0 else ""
        stats_text += f"• {city}: <b>{total_count}</b> человек{deleted_note}\n"

    total = total_active + total_deleted
    deleted_percentage = f" ({total_deleted/total:.1%} удаленных)" if total > 0 else ""
    stats_text += f"\nВсего: <b>{total}</b> человек{deleted_percentage}\n"

    # Count total guests (active registrations only)
    guest_cursor = app.collection.aggregate(
        [{"$group": {"_id": None, "total_guests": {"$sum": {"$ifNull": ["$guest_count", 0]}}}}]
    )
    guest_agg_result = await guest_cursor.to_list(length=None)
    total_guests = guest_agg_result[0]["total_guests"] if guest_agg_result else 0
    if total_guests > 0:
        stats_text += f"👥 Гостей: <b>{total_guests}</b>\n"
        stats_text += f"🎯 Всего участников (рег. + гости): <b>{total_active + total_guests}</b>\n"
    stats_text += "\n"

    # 2. Distribution by graduate type (combine active and deleted)
    # Active users
    active_grad_cursor = app.collection.aggregate(
        [
            {
                "$addFields": {
                    "normalized_type": {
                        "$toUpper": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$graduate_type", None]},
                                        {"$eq": [{"$toUpper": "$graduate_type"}, "GRADUATE"]},
                                    ]
                                },
                                "GRADUATE",
                                "$graduate_type",
                            ]
                        }
                    }
                }
            },
            {"$group": {"_id": "$normalized_type", "count": {"$sum": 1}}},
        ]
    )
    active_grad_stats = await active_grad_cursor.to_list(length=None)

    # Deleted users
    deleted_grad_cursor = app.deleted_users.aggregate(
        [
            {
                "$addFields": {
                    "normalized_type": {
                        "$toUpper": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$graduate_type", None]},
                                        {"$eq": [{"$toUpper": "$graduate_type"}, "GRADUATE"]},
                                    ]
                                },
                                "GRADUATE",
                                "$graduate_type",
                            ]
                        }
                    }
                }
            },
            {"$group": {"_id": "$normalized_type", "count": {"$sum": 1}}},
        ]
    )
    deleted_grad_stats = await deleted_grad_cursor.to_list(length=None)

    # Combine graduate type statistics
    grad_stats_combined = {}
    for stat in active_grad_stats:
        grad_type = stat["_id"] or "GRADUATE"
        count = stat["count"]
        grad_stats_combined[grad_type] = {"active": count, "deleted": 0}

    for stat in deleted_grad_stats:
        grad_type = stat["_id"] or "GRADUATE"
        count = stat["count"]
        if grad_type in grad_stats_combined:
            grad_stats_combined[grad_type]["deleted"] = count
        else:
            grad_stats_combined[grad_type] = {"active": 0, "deleted": count}

    stats_text += "<b>👥 По статусу:</b>\n"
    for grad_type, counts in sorted(grad_stats_combined.items()):
        active_count = counts["active"]
        deleted_count = counts["deleted"]
        total_count = active_count + deleted_count

        text = _format_graduate_type(grad_type.upper(), plural=total_count != 1)
        deleted_note = f" (из них {deleted_count} удал.)" if deleted_count > 0 else ""
        stats_text += f"• {text}: <b>{total_count}</b>{deleted_note}\n"
    stats_text += "\n"

    # 3. Payment statistics by city
    # Active users
    active_payment_cursor = app.collection.aggregate(
        [
            {"$match": {"target_city": {"$ne": "Санкт-Петербург"}}},  # Exclude SPb as it's free
            {"$match": {"target_city": {"$ne": "Белград"}}},  # Exclude Belgrade as it's free
            {"$match": {"graduate_type": {"$ne": "TEACHER"}}},  # Exclude teachers as they don't pay
            {
                "$group": {
                    "_id": "$target_city",
                    "payments": {
                        "$push": {
                            "payment": {"$ifNull": ["$payment_amount", 0]},
                            "formula": {"$ifNull": ["$formula_payment_amount", 0]},
                            "regular": {"$ifNull": ["$regular_payment_amount", 0]},
                            "discounted": {"$ifNull": ["$discounted_payment_amount", 0]},
                        }
                    },
                    "total_paid": {"$sum": {"$ifNull": ["$payment_amount", 0]}},
                    "confirmed_count": {
                        "$sum": {"$cond": [{"$eq": ["$payment_status", "confirmed"]}, 1, 0]}
                    },
                    "pending_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$payment_status", "pending"]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                    "declined_count": {
                        "$sum": {"$cond": [{"$eq": ["$payment_status", "declined"]}, 1, 0]}
                    },
                    "unpaid_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$payment_status", None]},
                                        {"$eq": ["$payment_status", "Не оплачено"]},
                                        {"$not": "$payment_status"},  # No payment_status field
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                }
            },
        ]
    )
    active_payment_stats = await active_payment_cursor.to_list(length=None)

    # Deleted users
    deleted_payment_cursor = app.deleted_users.aggregate(
        [
            {"$match": {"target_city": {"$ne": "Санкт-Петербург"}}},  # Exclude SPb as it's free
            {"$match": {"target_city": {"$ne": "Белград"}}},  # Exclude Belgrade as it's free
            {"$match": {"graduate_type": {"$ne": "TEACHER"}}},  # Exclude teachers as they don't pay
            {
                "$group": {
                    "_id": "$target_city",
                    "payments": {
                        "$push": {
                            "payment": {"$ifNull": ["$payment_amount", 0]},
                            "formula": {"$ifNull": ["$formula_payment_amount", 0]},
                            "regular": {"$ifNull": ["$regular_payment_amount", 0]},
                            "discounted": {"$ifNull": ["$discounted_payment_amount", 0]},
                        }
                    },
                    "total_paid": {"$sum": {"$ifNull": ["$payment_amount", 0]}},
                    "confirmed_count": {
                        "$sum": {"$cond": [{"$eq": ["$payment_status", "confirmed"]}, 1, 0]}
                    },
                    "pending_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$payment_status", "pending"]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                    "declined_count": {
                        "$sum": {"$cond": [{"$eq": ["$payment_status", "declined"]}, 1, 0]}
                    },
                    "unpaid_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$payment_status", None]},
                                        {"$eq": ["$payment_status", "Не оплачено"]},
                                        {"$not": "$payment_status"},  # No payment_status field
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                }
            },
        ]
    )
    deleted_payment_stats = await deleted_payment_cursor.to_list(length=None)

    # Combine payment statistics
    payment_stats_combined = {}

    # Process active payment stats
    for stat in active_payment_stats:
        city = stat["_id"]
        payment_stats_combined[city] = {"active": stat, "deleted": None}

    # Process deleted payment stats
    for stat in deleted_payment_stats:
        city = stat["_id"]
        if city in payment_stats_combined:
            payment_stats_combined[city]["deleted"] = stat
        else:
            payment_stats_combined[city] = {"active": None, "deleted": stat}

    stats_text += "<b>💰 Статистика оплат:</b>\n"
    total_paid_active = 0
    total_paid_deleted = 0
    total_formula_active = 0
    total_formula_deleted = 0
    total_regular_active = 0
    total_regular_deleted = 0
    total_discounted_active = 0
    total_discounted_deleted = 0

    # All ratios for final calculations
    all_ratios_formula = []
    all_ratios_regular = []
    all_ratios_discounted = []

    for city, stats in sorted(payment_stats_combined.items()):
        active_stat = stats["active"]
        deleted_stat = stats["deleted"]

        # Calculate totals and medians for active users
        active_paid = active_stat["total_paid"] if active_stat else 0
        active_payments = active_stat["payments"] if active_stat else []

        # Calculate totals and medians for deleted users
        deleted_paid = deleted_stat["total_paid"] if deleted_stat else 0
        deleted_payments = deleted_stat["payments"] if deleted_stat else []

        # Combine payments for median calculations
        all_payments = active_payments + deleted_payments

        # Calculate median percentages for all registrations
        paid_ratios_formula = []
        paid_ratios_regular = []
        paid_ratios_discounted = []

        for p in all_payments:
            if p["payment"] > 0:  # Only include those who paid
                if p["formula"] > 0:
                    ratio = (p["payment"] / p["formula"]) * 100
                    paid_ratios_formula.append(ratio)
                    all_ratios_formula.append(ratio)
                if p["regular"] > 0:
                    ratio = (p["payment"] / p["regular"]) * 100
                    paid_ratios_regular.append(ratio)
                    all_ratios_regular.append(ratio)
                if p["discounted"] > 0:
                    ratio = (p["payment"] / p["discounted"]) * 100
                    paid_ratios_discounted.append(ratio)
                    all_ratios_discounted.append(ratio)

        # Calculate medians
        median_formula = get_median(paid_ratios_formula)
        median_regular = get_median(paid_ratios_regular)
        median_discounted = get_median(paid_ratios_discounted)

        # Calculate totals for active users
        active_formula_total = sum(p["formula"] for p in active_payments)
        active_regular_total = sum(p["regular"] for p in active_payments)
        active_discounted_total = sum(p["discounted"] for p in active_payments)

        # Calculate totals for deleted users
        deleted_formula_total = sum(p["formula"] for p in deleted_payments)
        deleted_regular_total = sum(p["regular"] for p in deleted_payments)
        deleted_discounted_total = sum(p["discounted"] for p in deleted_payments)

        # Add to totals
        total_paid_active += active_paid
        total_paid_deleted += deleted_paid
        total_formula_active += active_formula_total
        total_formula_deleted += deleted_formula_total
        total_regular_active += active_regular_total
        total_regular_deleted += deleted_regular_total
        total_discounted_active += active_discounted_total
        total_discounted_deleted += deleted_discounted_total

        # Display city statistics
        total_paid = active_paid + deleted_paid
        deleted_note = f" (из них {deleted_paid:,} от удал.)" if deleted_paid > 0 else ""

        stats_text += f"\n<b>{city}:</b>\n"
        stats_text += f"💵 Собрано: <b>{total_paid:,}</b> руб.{deleted_note}\n"
        stats_text += f"📊 Медиана % от формулы: <i>{median_formula:.1f}%</i>\n"
        stats_text += f"📊 Медиана % от регулярной: <i>{median_regular:.1f}%</i>\n"
        stats_text += f"📊 Медиана % от мин. со скидкой: <i>{median_discounted:.1f}%</i>\n\n"

        # Payment status distribution
        stats_text += "<u>Статусы платежей (активные пользователи):</u>\n"
        if active_stat:
            stats_text += (
                f"✅ {PAYMENT_STATUS_MAP['confirmed']}: <b>{active_stat['confirmed_count']}</b>\n"
            )
            stats_text += (
                f"⏳ {PAYMENT_STATUS_MAP['pending']}: <b>{active_stat['pending_count']}</b>\n"
            )
            stats_text += f"⚪️ {PAYMENT_STATUS_MAP[None]}: <b>{active_stat['declined_count'] + active_stat['unpaid_count']}</b>\n"
        else:
            stats_text += "Нет активных пользователей\n"

        if deleted_stat and (
            deleted_stat["confirmed_count"] > 0 or deleted_stat["pending_count"] > 0
        ):
            stats_text += "\n<u>Удаленные пользователи с оплатами:</u>\n"
            if deleted_stat["confirmed_count"] > 0:
                stats_text += f"✅ {PAYMENT_STATUS_MAP['confirmed']}: <b>{deleted_stat['confirmed_count']}</b>\n"
            if deleted_stat["pending_count"] > 0:
                stats_text += (
                    f"⏳ {PAYMENT_STATUS_MAP['pending']}: <b>{deleted_stat['pending_count']}</b>\n"
                )

    # Add totals
    total_paid = total_paid_active + total_paid_deleted
    deleted_percentage = (
        f" ({total_paid_deleted/total_paid:.1%} от удаленных)" if total_paid > 0 else ""
    )

    if total_paid > 0:
        stats_text += f"\n<b>💵 Итого собрано: {total_paid:,} руб.</b>{deleted_percentage}\n"

        # Calculate overall medians
        total_median_formula = get_median(all_ratios_formula)
        total_median_regular = get_median(all_ratios_regular)
        total_median_discounted = get_median(all_ratios_discounted)

        stats_text += f"📊 Общая медиана % от формулы: <i>{total_median_formula:.1f}%</i>\n"
        stats_text += f"📊 Общая медиана % от регулярной: <i>{total_median_regular:.1f}%</i>\n"
        stats_text += (
            f"📊 Общая медиана % от мин. со скидкой: <i>{total_median_discounted:.1f}%</i>\n"
        )

    await send_safe(message.chat.id, stats_text)


@commands_menu.add_command(
    "simple_stats", "Краткая статистика регистраций", visibility=Visibility.ADMIN_ONLY
)
@router.message(Command("simple_stats"), AdminFilter())
async def show_simple_stats(message: Message, app: App):
    """Показать краткую статистику регистраций"""
    from app.app import PAYMENT_STATUS_MAP

    stats_text = "<b>📊 Краткая статистика регистраций</b> (включая удаленных)\n\n"

    # 1. Count registrations by city for both active and deleted users
    # Active users
    city_cursor = app.collection.aggregate(
        [{"$group": {"_id": "$target_city", "count": {"$sum": 1}}}]
    )
    active_city_stats = await city_cursor.to_list(length=None)

    # Deleted users
    deleted_city_cursor = app.deleted_users.aggregate(
        [{"$group": {"_id": "$target_city", "count": {"$sum": 1}}}]
    )
    deleted_city_stats = await deleted_city_cursor.to_list(length=None)

    # Combine city statistics
    city_stats_combined = {}
    for stat in active_city_stats:
        city = stat["_id"]
        count = stat["count"]
        city_stats_combined[city] = {"active": count, "deleted": 0}

    for stat in deleted_city_stats:
        city = stat["_id"]
        count = stat["count"]
        if city in city_stats_combined:
            city_stats_combined[city]["deleted"] = count
        else:
            city_stats_combined[city] = {"active": 0, "deleted": count}

    stats_text += "<b>🌆 По городам:</b>\n"
    total_active = 0
    total_deleted = 0

    for city, counts in sorted(city_stats_combined.items()):
        active_count = counts["active"]
        deleted_count = counts["deleted"]
        total_count = active_count + deleted_count

        total_active += active_count
        total_deleted += deleted_count

        deleted_note = f" (из них {deleted_count} удал.)" if deleted_count > 0 else ""
        stats_text += f"• {city}: <b>{total_count}</b> человек{deleted_note}\n"

    total = total_active + total_deleted
    deleted_percentage = f" ({total_deleted/total:.1%} удаленных)" if total > 0 else ""
    stats_text += f"\nВсего: <b>{total}</b> человек{deleted_percentage}\n\n"

    # 2. Distribution by graduate type (combine active and deleted)
    # Active users
    active_grad_cursor = app.collection.aggregate(
        [
            {
                "$addFields": {
                    "normalized_type": {
                        "$toUpper": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$graduate_type", None]},
                                        {"$eq": [{"$toUpper": "$graduate_type"}, "GRADUATE"]},
                                    ]
                                },
                                "GRADUATE",
                                "$graduate_type",
                            ]
                        }
                    }
                }
            },
            {"$group": {"_id": "$normalized_type", "count": {"$sum": 1}}},
        ]
    )
    active_grad_stats = await active_grad_cursor.to_list(length=None)

    # Deleted users
    deleted_grad_cursor = app.deleted_users.aggregate(
        [
            {
                "$addFields": {
                    "normalized_type": {
                        "$toUpper": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$graduate_type", None]},
                                        {"$eq": [{"$toUpper": "$graduate_type"}, "GRADUATE"]},
                                    ]
                                },
                                "GRADUATE",
                                "$graduate_type",
                            ]
                        }
                    }
                }
            },
            {"$group": {"_id": "$normalized_type", "count": {"$sum": 1}}},
        ]
    )
    deleted_grad_stats = await deleted_grad_cursor.to_list(length=None)

    # Combine graduate type statistics
    grad_stats_combined = {}
    for stat in active_grad_stats:
        grad_type = stat["_id"] or "GRADUATE"
        count = stat["count"]
        grad_stats_combined[grad_type] = {"active": count, "deleted": 0}

    for stat in deleted_grad_stats:
        grad_type = stat["_id"] or "GRADUATE"
        count = stat["count"]
        if grad_type in grad_stats_combined:
            grad_stats_combined[grad_type]["deleted"] = count
        else:
            grad_stats_combined[grad_type] = {"active": 0, "deleted": count}

    stats_text += "<b>👥 По статусу:</b>\n"
    for grad_type, counts in sorted(grad_stats_combined.items()):
        active_count = counts["active"]
        deleted_count = counts["deleted"]
        total_count = active_count + deleted_count

        text = _format_graduate_type(grad_type.upper(), plural=total_count != 1)
        deleted_note = f" (из них {deleted_count} удал.)" if deleted_count > 0 else ""
        stats_text += f"• {text}: <b>{total_count}</b>{deleted_note}\n"
    stats_text += "\n"

    # 3. Basic payment status distribution (active users)
    active_payment_cursor = app.collection.aggregate(
        [
            {"$match": {"target_city": {"$ne": "Санкт-Петербург"}}},  # Exclude SPb as it's free
            {"$match": {"target_city": {"$ne": "Белград"}}},  # Exclude Belgrade as it's free
            {"$match": {"graduate_type": {"$ne": "TEACHER"}}},  # Exclude teachers as they don't pay
            {
                "$group": {
                    "_id": "$target_city",
                    "confirmed_count": {
                        "$sum": {"$cond": [{"$eq": ["$payment_status", "confirmed"]}, 1, 0]}
                    },
                    "pending_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$payment_status", "pending"]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                    "declined_count": {
                        "$sum": {"$cond": [{"$eq": ["$payment_status", "declined"]}, 1, 0]}
                    },
                    "unpaid_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$payment_status", None]},
                                        {"$eq": ["$payment_status", "Не оплачено"]},
                                        {"$not": "$payment_status"},  # No payment_status field
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                    "total_paid": {"$sum": {"$ifNull": ["$payment_amount", 0]}},
                }
            },
        ]
    )
    active_payment_stats = await active_payment_cursor.to_list(length=None)

    # Deleted users payment stats
    deleted_payment_cursor = app.deleted_users.aggregate(
        [
            {"$match": {"target_city": {"$ne": "Санкт-Петербург"}}},  # Exclude SPb as it's free
            {"$match": {"target_city": {"$ne": "Белград"}}},  # Exclude Belgrade as it's free
            {"$match": {"graduate_type": {"$ne": "TEACHER"}}},  # Exclude teachers as they don't pay
            {
                "$group": {
                    "_id": "$target_city",
                    "confirmed_count": {
                        "$sum": {"$cond": [{"$eq": ["$payment_status", "confirmed"]}, 1, 0]}
                    },
                    "pending_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$payment_status", "pending"]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                    "declined_count": {
                        "$sum": {"$cond": [{"$eq": ["$payment_status", "declined"]}, 1, 0]}
                    },
                    "unpaid_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$payment_status", None]},
                                        {"$eq": ["$payment_status", "Не оплачено"]},
                                        {"$not": "$payment_status"},  # No payment_status field
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                    "total_paid": {"$sum": {"$ifNull": ["$payment_amount", 0]}},
                }
            },
        ]
    )
    deleted_payment_stats = await deleted_payment_cursor.to_list(length=None)

    # Combine payment stats
    payment_stats_combined = {}

    # Process active payment stats
    for stat in active_payment_stats:
        city = stat["_id"]
        payment_stats_combined[city] = {"active": stat, "deleted": None}

    # Process deleted payment stats
    for stat in deleted_payment_stats:
        city = stat["_id"]
        if city in payment_stats_combined:
            payment_stats_combined[city]["deleted"] = stat
        else:
            payment_stats_combined[city] = {"active": None, "deleted": stat}

    stats_text += "<b>💰 Статусы оплат:</b>\n"
    total_active_confirmed = 0
    total_active_pending = 0
    total_active_declined = 0
    total_active_unpaid = 0

    total_deleted_confirmed = 0
    total_deleted_pending = 0

    total_paid_active = 0
    total_paid_deleted = 0

    for city, stats in sorted(payment_stats_combined.items()):
        active_stat = stats["active"]
        deleted_stat = stats["deleted"]

        active_confirmed = active_stat["confirmed_count"] if active_stat else 0
        active_pending = active_stat["pending_count"] if active_stat else 0
        active_declined = active_stat["declined_count"] if active_stat else 0
        active_unpaid = active_stat["unpaid_count"] if active_stat else 0
        active_paid = active_stat["total_paid"] if active_stat else 0

        deleted_confirmed = deleted_stat["confirmed_count"] if deleted_stat else 0
        deleted_pending = deleted_stat["pending_count"] if deleted_stat else 0
        deleted_paid = deleted_stat["total_paid"] if deleted_stat else 0

        total_active_confirmed += active_confirmed
        total_active_pending += active_pending
        total_active_declined += active_declined
        total_active_unpaid += active_unpaid

        total_deleted_confirmed += deleted_confirmed
        total_deleted_pending += deleted_pending

        total_paid_active += active_paid
        total_paid_deleted += deleted_paid

        # Display for each city
        stats_text += f"\n<b>{city}:</b>\n"

        # Active users payment status
        total_active_statuses = active_confirmed + active_pending + active_declined + active_unpaid
        if total_active_statuses > 0:
            stats_text += f"✅ {PAYMENT_STATUS_MAP['confirmed']}: <b>{active_confirmed}</b>\n"
            stats_text += f"⏳ {PAYMENT_STATUS_MAP['pending']}: <b>{active_pending}</b>\n"
            stats_text += (
                f"⚪️ {PAYMENT_STATUS_MAP[None]}: <b>{active_declined + active_unpaid}</b>\n"
            )
        else:
            stats_text += "Нет активных пользователей\n"

        # Deleted users with payments
        if deleted_confirmed > 0 or deleted_pending > 0:
            stats_text += "\n<u>Удаленные пользователи с оплатами:</u>\n"
            if deleted_confirmed > 0:
                stats_text += f"✅ {PAYMENT_STATUS_MAP['confirmed']}: <b>{deleted_confirmed}</b>\n"
            if deleted_pending > 0:
                stats_text += f"⏳ {PAYMENT_STATUS_MAP['pending']}: <b>{deleted_pending}</b>\n"

        # Show payment amounts if any
        if active_paid > 0 or deleted_paid > 0:
            stats_text += "\n<u>Суммы платежей:</u>\n"
            if active_paid > 0:
                stats_text += f"💰 Активные: <b>{active_paid:,}</b> руб.\n"
            if deleted_paid > 0:
                stats_text += f"💰 Удаленные: <b>{deleted_paid:,}</b> руб.\n"

    # Add totals
    total_with_payment = (
        total_active_confirmed
        + total_active_pending
        + total_active_declined
        + total_active_unpaid
        + total_deleted_confirmed
        + total_deleted_pending
    )

    if total_with_payment > 0:
        stats_text += f"\n<b>Всего по статусам:</b>\n"

        # Active users
        stats_text += "<u>Активные пользователи:</u>\n"
        stats_text += f"✅ {PAYMENT_STATUS_MAP['confirmed']}: <b>{total_active_confirmed}</b>\n"
        stats_text += f"⏳ {PAYMENT_STATUS_MAP['pending']}: <b>{total_active_pending}</b>\n"
        stats_text += (
            f"⚪️ {PAYMENT_STATUS_MAP[None]}: <b>{total_active_declined + total_active_unpaid}</b>\n"
        )

        # Deleted users with payments
        if total_deleted_confirmed > 0 or total_deleted_pending > 0:
            stats_text += "\n<u>Удаленные пользователи с оплатами:</u>\n"
            if total_deleted_confirmed > 0:
                stats_text += (
                    f"✅ {PAYMENT_STATUS_MAP['confirmed']}: <b>{total_deleted_confirmed}</b>\n"
                )
            if total_deleted_pending > 0:
                stats_text += (
                    f"⏳ {PAYMENT_STATUS_MAP['pending']}: <b>{total_deleted_pending}</b>\n"
                )

        # Total payment amounts
        total_paid = total_paid_active + total_paid_deleted
        if total_paid > 0:
            deleted_percentage = (
                f" ({total_paid_deleted/total_paid:.1%} от удаленных)" if total_paid > 0 else ""
            )
            stats_text += f"\n<b>💵 Итого собрано: {total_paid:,} руб.</b>{deleted_percentage}\n"

    await send_safe(message.chat.id, stats_text)


@commands_menu.add_command(
    "year_stats", "Статистика регистраций по годам выпуска", visibility=Visibility.ADMIN_ONLY
)
@router.message(Command("year_stats"), AdminFilter())
async def show_year_stats(message: Message, app: App):
    """Show registration statistics by graduation year with matplotlib diagrams"""

    # Send status message
    status_msg = await send_safe(message.chat.id, "⏳ Генерация статистики по годам выпуска...")

    # Get all active registrations
    cursor = app.collection.find(
        {
            "graduation_year": {
                "$exists": True,
                "$ne": 0,
            },  # Filter out teachers and others without graduation year
        }
    )
    active_registrations = await cursor.to_list(length=None)

    # Get all deleted registrations for text stats only
    deleted_cursor = app.deleted_users.find(
        {
            "graduation_year": {
                "$exists": True,
                "$ne": 0,
            },  # Filter out teachers and others without graduation year
        }
    )
    deleted_registrations = await deleted_cursor.to_list(length=None)

    # Add a flag to identify the source of each registration
    for reg in active_registrations:
        reg["is_deleted"] = False
    for reg in deleted_registrations:
        reg["is_deleted"] = True

    # We'll use only active registrations for the visualizations
    visualizations_regs = active_registrations

    # Combine both sets for text stats
    all_registrations = active_registrations + deleted_registrations

    if not active_registrations:
        await status_msg.edit_text("❌ Нет данных о регистрациях с указанным годом выпуска.")
        return

    # Group registrations by city and year for text stats
    cities = ["Москва", "Пермь", "Санкт-Петербург", "Белград"]
    city_year_counts = {}
    city_year_counts_deleted = {}

    for city in cities:
        city_year_counts[city] = defaultdict(int)
        city_year_counts_deleted[city] = defaultdict(int)

    all_years = set()

    for reg in all_registrations:
        city = reg.get("target_city")
        year = reg.get("graduation_year")
        is_deleted = reg.get("is_deleted", False)

        # Skip registrations without valid graduation year (teachers, etc.)
        if not year or year == 0 or city not in cities:
            continue

        # Count by city and year
        if is_deleted:
            city_year_counts_deleted[city][year] += 1
        else:
            city_year_counts[city][year] += 1
        all_years.add(year)

    # Group years into 5-year periods for text statistics
    min_year = min(all_years)
    max_year = max(all_years)

    # Round min_year down to the nearest multiple of 5
    period_start = min_year - (min_year % 5)

    # Create periods (e.g. 1995-1999, 2000-2004, etc.)
    periods = []
    period_labels = []
    current = period_start

    while current <= max_year:
        period_end = current + 4
        periods.append((current, period_end))
        period_labels.append(f"{current}-{period_end}")
        current += 5

    # Count registrations by period for each city
    period_counts = {city: [0] * len(periods) for city in cities}
    period_counts_deleted = {city: [0] * len(periods) for city in cities}

    for city in cities:
        for year, count in city_year_counts[city].items():
            # Find which period this year belongs to
            for i, (start, end) in enumerate(periods):
                if start <= year <= end:
                    period_counts[city][i] += count
                    break

        for year, count in city_year_counts_deleted[city].items():
            # Find which period this year belongs to
            for i, (start, end) in enumerate(periods):
                if start <= year <= end:
                    period_counts_deleted[city][i] += count
                    break

    # Prepare the summary statistics text
    stats_text = "<b>📊 Статистика регистраций по годам выпуска</b> (текст включает удаленных)\n\n"

    # Add total registrations per period
    stats_text += "<b>🎓 По периодам (все города):</b>\n"

    for i, period in enumerate(period_labels):
        period_total_active = sum(period_counts[city][i] for city in cities)
        period_total_deleted = sum(period_counts_deleted[city][i] for city in cities)
        period_total = period_total_active + period_total_deleted

        deleted_note = f" (из них {period_total_deleted} удал.)" if period_total_deleted > 0 else ""
        stats_text += f"• {period}: <b>{period_total}</b> человек{deleted_note}\n"

    # Add city breakdown
    for city in cities:
        stats_text += f"\n<b>🏙️ {city}:</b>\n"
        for i, period in enumerate(period_labels):
            active_count = period_counts[city][i]
            deleted_count = period_counts_deleted[city][i]
            total_count = active_count + deleted_count

            deleted_note = f" (из них {deleted_count} удал.)" if deleted_count > 0 else ""
            stats_text += f"• {period}: <b>{total_count}</b> человек{deleted_note}\n"

    # Convert data to pandas DataFrame for seaborn - ONLY ACTIVE USERS FOR VISUALS
    data = []
    sorted_years = sorted(all_years)

    for city in cities:
        for year in sorted_years:
            active_count = city_year_counts[city].get(year, 0)

            if active_count > 0:  # Only include non-zero values for active users
                data.append({"Город": city, "Год выпуска": year, "Количество": active_count})

    df = pd.DataFrame(data)

    # Plot for active users only
    plt.figure(figsize=(15, 8), dpi=100)

    # Define the color palette for cities
    city_palette = {
        "Москва": "#FF6666",  # stronger red
        "Пермь": "#5599FF",  # stronger blue
        "Санкт-Петербург": "#66CC66",  # stronger green
        "Белград": "#FF00FF",  # stronger purple
    }

    # Use seaborn with custom styling
    sns.set_style("whitegrid")

    # Create the bar plot by city (only active users)
    ax = sns.barplot(
        data=df, x="Год выпуска", y="Количество", hue="Город", palette=city_palette, errorbar=None
    )

    # Add annotations for each bar
    for container in ax.containers:
        ax.bar_label(container, fontsize=9, fontweight="bold", padding=3)

    # Enhance the plot with better styling
    plt.title(
        "Количество регистраций по годам выпуска и городам\n(только активные)", fontsize=18, pad=20
    )
    plt.xlabel("Год выпуска", fontsize=14, labelpad=10)
    plt.ylabel("Количество человек", fontsize=14, labelpad=10)
    plt.xticks(rotation=45)
    plt.legend(title="Город", fontsize=12, title_fontsize=14)

    # Adjust layout
    plt.tight_layout()

    # Save the plot to a bytes buffer
    buf_all_cities = io.BytesIO()
    plt.savefig(buf_all_cities, format="png")
    buf_all_cities.seek(0)
    plt.close()

    # Send the stats text and diagrams
    await status_msg.delete()

    # Send the text first
    await send_safe(message.chat.id, stats_text, parse_mode="HTML")

    # Send the diagrams
    await message.answer_photo(
        BufferedInputFile(buf_all_cities.getvalue(), filename="registration_stats_by_city.png"),
        caption="📊 Регистрации по годам выпуска и городам",
    )


@commands_menu.add_command(
    "five_year_stats", "График по пятилеткам выпуска", visibility=Visibility.ADMIN_ONLY
)
@router.message(Command("five_year_stats"), AdminFilter())
async def show_five_year_stats(message: Message, app: App):
    """Показать график регистраций по пятилеткам выпуска и городам"""

    # Send status message
    status_msg = await send_safe(message.chat.id, "⏳ Генерация графика по пятилеткам выпуска...")

    # Get all active registrations
    cursor = app.collection.find(
        {
            "graduation_year": {
                "$exists": True,
                "$ne": 0,
            },  # Filter out entries without graduation year
        }
    )
    active_registrations = await cursor.to_list(length=None)

    # Get deleted registrations (only for text statistics)
    deleted_cursor = app.deleted_users.find(
        {
            "graduation_year": {
                "$exists": True,
                "$ne": 0,
            },  # Filter out entries without graduation year
        }
    )
    deleted_registrations = await deleted_cursor.to_list(length=None)

    if not active_registrations:
        await status_msg.edit_text("❌ Нет данных о регистрациях с указанным годом выпуска.")
        return

    # Convert MongoDB records to pandas DataFrame - ONLY ACTIVE USERS for visualization
    df = pd.DataFrame(active_registrations)

    # Обработка годов выпуска
    df["graduation_year"] = pd.to_numeric(df["graduation_year"], errors="coerce")
    df = df.dropna(subset=["graduation_year"])
    df["Пятилетка"] = df["graduation_year"].apply(lambda y: f"{int(y)//5*5}–{int(y)//5*5 + 4}")

    # Упрощённая категоризация городов
    def simplify_city(city):
        if pd.isna(city):
            return "Другие"
        city = str(city).strip().lower()
        if "перм" in city:
            return "Пермь"
        elif "моск" in city:
            return "Москва"
        elif "спб" in city or "питер" in city or "санкт" in city:
            return "Санкт-Петербург"
        elif "белград" in city:
            return "Белград"
        else:
            return "Другие"

    df["Город (укрупнённо)"] = df["target_city"].apply(simplify_city)

    # Группировка по пятилеткам и городам
    pivot = (
        df.groupby(["Пятилетка", "Город (укрупнённо)"])["full_name"]
        .count()
        .unstack()
        .fillna(0)
        .sort_index()
    )

    # Упорядочим колонки
    city_order = ["Пермь", "Москва", "Санкт-Петербург", "Белград", "Другие"]
    available_cities = [c for c in city_order if c in pivot.columns]
    if available_cities:
        pivot = pivot[available_cities]

    # Построение графика
    plt.figure(figsize=(12, 7), dpi=100)
    ax = pivot.plot(kind="bar", stacked=True, figsize=(12, 7), colormap="Set2")

    plt.title("Зарегистрировавшиеся по пятилеткам выпуска (только активные)")
    plt.xlabel("Пятилетка")
    plt.ylabel("Количество участников")
    plt.xticks(rotation=45)
    plt.legend(title="Город", bbox_to_anchor=(1.05, 1), loc="upper left")
    plt.tight_layout()
    plt.grid(axis="y")

    # Подписи на графике
    for bar_idx, (idx, row) in enumerate(pivot.iterrows()):
        cumulative = 0
        for city in pivot.columns:
            value = row[city]
            if value > 0:
                ax.text(
                    x=bar_idx,
                    y=cumulative + value / 2,
                    s=int(value),
                    ha="center",
                    va="center",
                    fontsize=9,
                )
                cumulative += value

    # Save the plot to a bytes buffer
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close()

    # Calculate total stats (including deleted) for caption
    active_count = len(active_registrations)
    deleted_count = len(deleted_registrations)
    total_count = active_count + deleted_count

    # Delete status message
    await status_msg.delete()

    # Send the diagram with informative caption
    caption = f"📊 Зарегистрировавшиеся по пятилеткам выпуска и городам\n"
    caption += f"График показывает только {active_count} активных участников\n"
    if deleted_count > 0:
        caption += f"(в статистике также есть {deleted_count} удаленных участников, не показанных на графике)"

    await message.answer_photo(
        BufferedInputFile(buf.getvalue(), filename="five_year_stats.png"),
        caption=caption,
    )


@commands_menu.add_command(
    "payment_stats", "Круговая диаграмма оплат", visibility=Visibility.ADMIN_ONLY
)
@router.message(Command("payment_stats"), AdminFilter())
async def show_payment_stats(message: Message, app: App):
    """Показать круговую диаграмму оплат по пятилеткам выпуска"""

    # Send status message
    status_msg = await send_safe(message.chat.id, "⏳ Генерация круговой диаграммы оплат...")

    # Get all registrations with payments from active users
    cursor = app.collection.find(
        {
            "graduation_year": {
                "$exists": True,
                "$ne": 0,
            },  # Filter out entries without graduation year
            "payment_status": "confirmed",  # Only include confirmed payments
            "payment_amount": {"$gt": 0},  # Only include payments > 0
        }
    )
    active_registrations = await cursor.to_list(length=None)

    # Get all registrations with payments from deleted users (only for stats)
    deleted_cursor = app.deleted_users.find(
        {
            "graduation_year": {
                "$exists": True,
                "$ne": 0,
            },  # Filter out entries without graduation year
            "payment_status": "confirmed",  # Only include confirmed payments
            "payment_amount": {"$gt": 0},  # Only include payments > 0
        }
    )
    deleted_registrations = await deleted_cursor.to_list(length=None)

    if not active_registrations:
        await status_msg.edit_text("❌ Нет данных об оплатах с указанным годом выпуска.")
        return

    # Convert MongoDB records to pandas DataFrame - ONLY ACTIVE USERS
    df = pd.DataFrame(active_registrations)

    # Обработка годов выпуска
    df["graduation_year"] = pd.to_numeric(df["graduation_year"], errors="coerce")
    df = df.dropna(subset=["graduation_year"])
    df["Пятилетка"] = df["graduation_year"].apply(lambda y: f"{int(y)//5*5}–{int(y)//5*5 + 4}")

    # Группировка и сумма по пятилеткам
    donation_by_period = df.groupby("Пятилетка")["payment_amount"].sum()
    donation_by_period = donation_by_period[donation_by_period > 0].sort_index()

    # Calculate statistics including deleted users for reporting
    status_stats = {
        "active": len(active_registrations),
        "deleted": len(deleted_registrations),
        "active_sum": sum(reg.get("payment_amount", 0) for reg in active_registrations),
        "deleted_sum": sum(reg.get("payment_amount", 0) for reg in deleted_registrations),
    }

    # Построение круговой диаграммы
    plt.figure(figsize=(10, 10), dpi=100)

    # Get a nicer color palette
    colors = plt.cm.Set3.colors[: len(donation_by_period)]

    # Add percentage and absolute values to the labels
    total = donation_by_period.sum()
    labels = [
        f"{period}: {amount:,.0f} ₽ ({amount/total:.1%})"
        for period, amount in zip(donation_by_period.index, donation_by_period.values)
    ]

    plt.pie(
        donation_by_period.values,
        labels=labels,
        autopct="",  # We already added percentages to labels
        startangle=90,
        colors=colors,
        shadow=False,
        wedgeprops={"linewidth": 1, "edgecolor": "white"},
    )

    plt.title(
        "Суммарные оплаты по пятилеткам выпуска\n(только активные участники)", fontsize=16, pad=20
    )
    plt.tight_layout()

    # Save the plot to a bytes buffer
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close()

    # Delete status message
    await status_msg.delete()

    # Create caption with summary info
    caption = "💰 Суммарные оплаты по пятилеткам выпуска (график: только активные участники)"

    if status_stats["deleted"] > 0:
        caption += f"\n\nВсего: {status_stats['active_sum'] + status_stats['deleted_sum']:,.0f} ₽"
        caption += (
            f"\n• Активные ({status_stats['active']} чел.): {status_stats['active_sum']:,.0f} ₽"
        )
        caption += (
            f"\n• Удаленные ({status_stats['deleted']} чел.): {status_stats['deleted_sum']:,.0f} ₽"
        )

    # Send the diagram
    await message.answer_photo(
        BufferedInputFile(buf.getvalue(), filename="payment_stats.png"),
        caption=caption,
    )

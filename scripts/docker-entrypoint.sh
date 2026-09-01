#!/bin/sh
set -eu

# The managed-platform bootstrap may start as root solely so a newly mounted
# volume can be handed to the unprivileged application user.  Keep this list
# deliberately narrow: never chown an arbitrary environment-provided path.
configured_data_dir=${BILLGITBOARD_DATA_DIR:-/data}
case "$configured_data_dir" in
    /*) ;;
    *)
        echo "BILLGITBOARD_DATA_DIR must be an absolute container path" >&2
        exit 64
        ;;
esac

resolved_data_dir=$(realpath -m -- "$configured_data_dir")
case "$resolved_data_dir" in
    /data | /data/* | /var/data/*) ;;
    *)
        echo "Refusing unsafe BILLGITBOARD_DATA_DIR: $resolved_data_dir" >&2
        echo "Allowed container roots are /data and a child of /var/data" >&2
        exit 64
        ;;
esac

if [ "$resolved_data_dir" = "/" ]; then
    echo "Refusing to use the filesystem root as BILLGITBOARD_DATA_DIR" >&2
    exit 64
fi

export BILLGITBOARD_DATA_DIR=$resolved_data_dir
umask 077

current_uid=$(id -u)
if [ "$current_uid" = "0" ]; then
    mkdir -p -- "$resolved_data_dir"
    # The umask above makes any intermediate directory mkdir -p had to create
    # 0700 root-owned, and the chown below only reaches the data directory
    # itself. A path such as /var/data/billgitboard would then leave /var/data
    # untraversable, and the unprivileged re-entry below would fail with
    # "Permission denied" on the parent rather than on the data directory.
    data_parent=$(dirname -- "$resolved_data_dir")
    if [ "$data_parent" != "/" ]; then
        chmod 0755 -- "$data_parent"
    fi
    data_owner=$(stat -c '%u:%g' -- "$resolved_data_dir")
    if [ "$data_owner" != "10001:10001" ]; then
        # Repair a fresh/root-owned managed mount once. On later restarts the
        # top directory already proves this is the app-owned tree, so avoid an
        # unnecessary traversal of private 0700 job directories.
        chown -R 10001:10001 -- "$resolved_data_dir"
    fi
    # Re-enter this script after setpriv so a silent inability to clear the
    # bounding set (for example, a missing CAP_SETPCAP) cannot go unnoticed.
    BILLGITBOARD_VERIFY_PRIVILEGE_DROP=1
    export BILLGITBOARD_VERIFY_PRIVILEGE_DROP
    exec setpriv \
        --reuid=billgitboard \
        --regid=billgitboard \
        --init-groups \
        --no-new-privs \
        --bounding-set=-all \
        --inh-caps=-all \
        --ambient-caps=-all \
        "$0" "$@"
fi

if [ "$current_uid" != "10001" ]; then
    echo "BillGitBoard must run as root bootstrap or UID 10001, not UID $current_uid" >&2
    exit 64
fi

mkdir -p -- "$resolved_data_dir"
if [ ! -w "$resolved_data_dir" ]; then
    echo "BILLGITBOARD_DATA_DIR is not writable by UID 10001: $resolved_data_dir" >&2
    exit 73
fi

if [ "${BILLGITBOARD_VERIFY_PRIVILEGE_DROP:-0}" = "1" ]; then
    # no_new_privs is checked first because the bounding-set verdict below
    # depends on it.
    no_new_privs=$(awk '$1 == "NoNewPrivs:" { print $2 }' /proc/self/status)
    if [ "$no_new_privs" != "1" ]; then
        echo "Privilege drop did not enable no_new_privs" >&2
        exit 77
    fi

    # These four are the privileges this process actually holds. Any of them
    # surviving the drop means the drop did not happen, so refuse to serve.
    for capability_field in CapInh CapPrm CapEff CapAmb; do
        capability_value=$(awk -v key="$capability_field:" '$1 == key { print $2 }' /proc/self/status)
        case "$capability_value" in
            "" | *[!0]*)
                echo "Privilege drop left $capability_field non-zero: $capability_value" >&2
                echo "Refusing to serve with capabilities still held" >&2
                exit 77
                ;;
        esac
    done

    # The bounding set is different: it holds no privilege itself, it only caps
    # what an execve could ever grant. Clearing it needs CAP_SETPCAP, which some
    # managed runtimes (Render among them) do not give the container, and
    # setpriv cannot report that failure. With no_new_privs set and all four
    # sets above empty, no execve can add a capability, so a residual bounding
    # set cannot be turned into privilege. Report it and carry on.
    bounding_set=$(awk '$1 == "CapBnd:" { print $2 }' /proc/self/status)
    case "$bounding_set" in
        "" | *[!0]*)
            echo "Note: capability bounding set not cleared (CapBnd: $bounding_set)." >&2
            echo "CAP_SETPCAP is unavailable here; no_new_privs is set and no capability" >&2
            echo "is held, so nothing can be acquired. Continuing." >&2
            ;;
    esac
fi

exec "$@"

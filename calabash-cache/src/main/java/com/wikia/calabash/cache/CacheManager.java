package com.wikia.calabash.cache;

import com.google.common.util.concurrent.ListeningExecutorService;
import com.google.common.util.concurrent.MoreExecutors;
import com.wikia.calabash.cache.guava.LocalCache;
import com.wikia.calabash.cache.guava.LocalCached;
import com.wikia.calabash.cache.redis.RedisCache;
import com.wikia.calabash.cache.redis.RedisCached;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Component;

import javax.annotation.Resource;
import java.lang.reflect.Method;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

@Component
public class CacheManager {
    private static ConcurrentHashMap<String, RedisCache> redisCaches = new ConcurrentHashMap<>();
    private static ConcurrentHashMap<String, LocalCache> localCaches = new ConcurrentHashMap<>();

    @Resource
    private RedisTemplate<String, String> redisTemplate;

    private ListeningExecutorService refreshListeningExecutor;

    @Autowired(required = false)
    public CacheManager(@Autowired(required = false) ExecutorService localCacheRefreshExecutor) {
        if (localCacheRefreshExecutor != null) {
            this.refreshListeningExecutor = MoreExecutors.listeningDecorator(localCacheRefreshExecutor);
        } else {
            ThreadPoolExecutor threadPoolExecutor = new ThreadPoolExecutor(20, 200, 5, TimeUnit.MINUTES, new LinkedBlockingQueue<>(), r -> new Thread(r, "Local-Cache-Refresh-Thread"));
            this.refreshListeningExecutor = MoreExecutors.listeningDecorator(threadPoolExecutor);
        }
    }

    public void addRedisCache(RedisCached redisCached, Method cachedMethod) {
        redisCaches.put(redisCached.name(), new RedisCache(
                redisTemplate
                , cachedMethod
                , redisCached
        ));
    }

    public void addLocalCache(LocalCached localCached, Method method, Object methodProxy) {
        localCaches.put(localCached.name(), new LocalCache(
                refreshListeningExecutor
                , localCached
                , method
                , methodProxy
        ));
    }

    public RedisCache getRedisCache(String name) {
        return redisCaches.get(name);
    }

    public LocalCache getLocalCache(String name) {
        return localCaches.get(name);
    }


}

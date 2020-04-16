package com.wikia.calabash.cache;

import com.google.common.base.Joiner;
import org.springframework.core.DefaultParameterNameDiscoverer;
import org.springframework.expression.EvaluationContext;
import org.springframework.expression.Expression;
import org.springframework.expression.spel.standard.SpelExpressionParser;
import org.springframework.expression.spel.support.StandardEvaluationContext;

import java.lang.reflect.Method;

public class SpelKeyParser implements KeyParser {
    private static final Joiner VERTICAL_JOINER = Joiner.on("|");
    /**
     * 用于SpEL表达式解析.
     */
    private SpelExpressionParser parser = new SpelExpressionParser();
    /**
     * 用于获取方法参数定义名字.
     */
    private DefaultParameterNameDiscoverer nameDiscoverer = new DefaultParameterNameDiscoverer();

    public String generateKey(String name, String key, Method method, Object[] args) {
        String parsedKey;
        if (key == null || key.isEmpty()) {
            parsedKey = generateKey(args);
        } else {
            parsedKey = generateKeyBySpEL(key, method, args);
        }
        return name + ":" + parsedKey;
    }

    @Override
    public Object[] parseKey(String key, Method method) {
        // todo 实现此方法
        throw new RuntimeException("方法暂未实现");
    }

    /**
     * 默认缓存key生成器.
     * 注解中key不传参，参数生成key.
     */
    private String generateKey(Object[] args) {
        return VERTICAL_JOINER.join(args);
    }

    /**
     * SpEL表达式缓存Key生成器.
     * 注解中传入key参数，则使用此生成器生成缓存.
     */
    private String generateKeyBySpEL(String spELString, Method method, Object[] args) {
        String[] paramNames = nameDiscoverer.getParameterNames(method);
        if (paramNames != null) {
            Expression expression = parser.parseExpression(spELString);
            EvaluationContext context = new StandardEvaluationContext();
            for (int i = 0; i < args.length; i++) {
                context.setVariable(paramNames[i], args[i]);
            }
            Object value = expression.getValue(context);
            if (value == null) {
                throw new IllegalArgumentException(String.format("local cache el key illegal:%s, %s", method, spELString));
            }
            return value.toString();
        }
        return spELString;
    }
}
